"""Wire protocol for Meshtastic C2 messages.

Messages are plain text, pipe-delimited. First field is the tag that identifies
the message type. Literal '|' inside a text field is escaped as '%7C'.

Two acknowledgement forms:
- ACK (central -> agent): acknowledges a sequenced message (DET/STAT/LOG) by seq
- RES (agent -> central): reports the result of a command (CMD/CFG/APPROVE)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any


class ProtocolError(ValueError):
    """Raised when a message cannot be parsed."""


_TAGS = {"CMD", "CFG", "CFGINFO", "SCANINFO", "APPROVE", "ACK", "RES", "HELLO", "STAT", "DET", "LOG"}


def _esc(s: str) -> str:
    return str(s).replace("|", "%7C")


def _unesc(s: str) -> str:
    return s.replace("%7C", "|")


@dataclass
class Message:
    tag: str
    agent_id: str
    seq: Optional[int]          # set for DET/STAT/LOG/ACK, None otherwise
    fields: Dict[str, Any]
    raw: str


# -- encoders ---------------------------------------------------------------

def encode_cmd(target_id: str, seq: int, verb: str, args: List[str]) -> str:
    """Server->agent command.

    `seq` is allocated by the server's ServerOutbox so the agent can ACK
    individual commands and the outbox can retry unacked ones with
    exponential backoff. Broadcast target "*" is still allowed; the
    server simply won't track ACKs for non-unicast CMDs.
    """
    parts = ["CMD", target_id, str(int(seq)), verb] + [_esc(a) for a in args]
    return "|".join(parts)


def encode_cfg(target_id: str, seq: int, key: str, value: str) -> str:
    """Server->agent config set. See encode_cmd re: seq semantics."""
    return f"CFG|{target_id}|{int(seq)}|{_esc(key)}|{_esc(value)}"


def encode_approve(agent_id: str) -> str:
    return f"APPROVE|{agent_id}"


def encode_ack(agent_id: str, seq: int, status: str = "ok") -> str:
    return f"ACK|{agent_id}|{seq}|{_esc(status)}"


def encode_res(agent_id: str, verb: str, result: str, msg: str = "") -> str:
    return f"RES|{agent_id}|{_esc(verb)}|{_esc(result)}|{_esc(msg)}"


def encode_hello(agent_id: str, version: str, hw: str) -> str:
    return f"HELLO|{agent_id}|{_esc(version)}|{_esc(hw)}"


def encode_stat(agent_id: str, seq: int, scanner: str, state: str,
                lat: Optional[float], lon: Optional[float],
                sats: int, cpu: int, uptime_sec: int) -> str:
    lat_s = f"{lat:.4f}" if lat is not None else ""
    lon_s = f"{lon:.4f}" if lon is not None else ""
    return (f"STAT|{agent_id}|{seq}|{_esc(scanner)}|{_esc(state)}|"
            f"{lat_s}|{lon_s}|{sats}|{cpu}|{uptime_sec}")


def encode_det(agent_id: str, seq: int, type_: str, freq_mhz: float,
               rssi: int, lat: Optional[float], lon: Optional[float],
               ts_unix: int, summary: str = "",
               snr: Optional[int] = None) -> str:
    lat_s = f"{lat:.4f}" if lat is not None else ""
    lon_s = f"{lon:.4f}" if lon is not None else ""
    base = (f"DET|{agent_id}|{seq}|{_esc(type_)}|{freq_mhz:.5f}|{rssi}|"
            f"{lat_s}|{lon_s}|{ts_unix}|{_esc(summary)}")
    if snr is None:
        return base
    return f"{base}|{snr}"


def encode_det_truncated(agent_id: str, seq: int, type_: str, freq_mhz: float,
                          rssi: int, lat: Optional[float], lon: Optional[float],
                          ts_unix: int, summary: str,
                          snr: Optional[int] = None,
                          max_bytes: int = 200) -> str:
    """Encode DET, progressively dropping optional tail fields if oversized.

    Drop order: summary -> lat/lon -> ts_unix (field becomes empty). SNR is
    preserved across drops — it's small and the server needs it to compute
    the real noise floor."""
    attempts = [
        (summary, lat, lon, ts_unix),
        ("", lat, lon, ts_unix),
        ("", None, None, ts_unix),
        ("", None, None, 0),
    ]
    for s, la, lo, ts in attempts:
        ts_eff = ts if ts else 0
        wire = encode_det(agent_id, seq, type_, freq_mhz, rssi, la, lo,
                          ts_eff, s, snr=snr)
        if len(wire.encode("utf-8")) <= max_bytes:
            return wire
    return wire  # best effort


def encode_log(agent_id: str, seq: int, level: str, text: str) -> str:
    return f"LOG|{agent_id}|{seq}|{_esc(level)}|{_esc(text)}"


def encode_cfginfo(agent_id: str, seq: int, mesh_channel_index: int,
                   meshtastic_port: str, gps_port: str,
                   state_dir: str, version: str, hw: str) -> str:
    """One-shot snapshot of the agent's static config, sent at startup
    so the dashboard can render the agent's "Config" view."""
    return (f"CFGINFO|{agent_id}|{seq}|{mesh_channel_index}|"
            f"{_esc(meshtastic_port)}|{_esc(gps_port)}|{_esc(state_dir)}|"
            f"{_esc(version)}|{_esc(hw)}")


def encode_scaninfo(agent_id: str, seq: int, scanner_type: str,
                    center_mhz: float, bw_mhz: float,
                    channels: int, hopping: bool, parsers: str) -> str:
    """Snapshot of the agent's currently running scanner. Empty
    `scanner_type` means no scanner is running (after STOP)."""
    return (f"SCANINFO|{agent_id}|{seq}|{_esc(scanner_type)}|"
            f"{center_mhz:.4f}|{bw_mhz:.4f}|{channels}|"
            f"{1 if hopping else 0}|{_esc(parsers)}")


# -- decoder ----------------------------------------------------------------

def decode(wire: str) -> Message:
    if not wire:
        raise ProtocolError("empty message")
    parts = wire.split("|")
    tag = parts[0]
    if tag not in _TAGS:
        raise ProtocolError(f"unknown tag: {tag!r}")
    try:
        if tag == "CMD":
            # New (with seq) format: CMD|<target>|<seq>|<verb>|<args...>
            _check_min(parts, 4)
            return Message(tag, parts[1], int(parts[2]),
                           {"verb": parts[3], "args": [_unesc(p) for p in parts[4:]]},
                           raw=wire)
        if tag == "CFG":
            # New (with seq) format: CFG|<target>|<seq>|<key>|<value>
            _check_min(parts, 5)
            return Message(tag, parts[1], int(parts[2]),
                           {"key": _unesc(parts[3]), "value": _unesc(parts[4])},
                           raw=wire)
        if tag == "APPROVE":
            _check_min(parts, 2)
            return Message(tag, parts[1], None, {}, raw=wire)
        if tag == "ACK":
            _check_min(parts, 4)
            return Message(tag, parts[1], int(parts[2]),
                           {"seq": int(parts[2]), "status": _unesc(parts[3])},
                           raw=wire)
        if tag == "RES":
            _check_min(parts, 4)
            return Message(tag, parts[1], None,
                           {"verb": _unesc(parts[2]),
                            "result": _unesc(parts[3]),
                            "msg": _unesc(parts[4]) if len(parts) > 4 else ""},
                           raw=wire)
        if tag == "HELLO":
            _check_min(parts, 4)
            return Message(tag, parts[1], None,
                           {"version": _unesc(parts[2]), "hw": _unesc(parts[3])},
                           raw=wire)
        if tag == "STAT":
            _check_min(parts, 10)
            return Message(tag, parts[1], int(parts[2]),
                           {"scanner": _unesc(parts[3]),
                            "state": _unesc(parts[4]),
                            "lat": float(parts[5]) if parts[5] else None,
                            "lon": float(parts[6]) if parts[6] else None,
                            "sats": int(parts[7]) if parts[7] else 0,
                            "cpu": int(parts[8]) if parts[8] else 0,
                            "uptime_sec": int(parts[9]) if parts[9] else 0},
                           raw=wire)
        if tag == "DET":
            _check_min(parts, 10)
            snr = None
            if len(parts) > 10 and parts[10]:
                try:
                    snr = int(parts[10])
                except ValueError:
                    snr = None
            return Message(tag, parts[1], int(parts[2]),
                           {"type": _unesc(parts[3]),
                            "freq_mhz": float(parts[4]) if parts[4] else 0.0,
                            "rssi": int(parts[5]) if parts[5] else 0,
                            "lat": float(parts[6]) if parts[6] else None,
                            "lon": float(parts[7]) if parts[7] else None,
                            "ts_unix": int(parts[8]) if parts[8] else 0,
                            "summary": _unesc(parts[9]) if len(parts) > 9 else "",
                            "snr": snr},
                           raw=wire)
        if tag == "LOG":
            _check_min(parts, 5)
            return Message(tag, parts[1], int(parts[2]),
                           {"level": _unesc(parts[3]),
                            "text": _unesc(parts[4])},
                           raw=wire)
        if tag == "CFGINFO":
            _check_min(parts, 9)
            return Message(tag, parts[1], int(parts[2]),
                           {"mesh_channel_index": int(parts[3]) if parts[3] else 0,
                            "meshtastic_port": _unesc(parts[4]),
                            "gps_port": _unesc(parts[5]),
                            "state_dir": _unesc(parts[6]),
                            "version": _unesc(parts[7]),
                            "hw": _unesc(parts[8])},
                           raw=wire)
        if tag == "SCANINFO":
            _check_min(parts, 9)
            return Message(tag, parts[1], int(parts[2]),
                           {"scanner_type": _unesc(parts[3]),
                            "center_mhz": float(parts[4]) if parts[4] else 0.0,
                            "bw_mhz": float(parts[5]) if parts[5] else 0.0,
                            "channels": int(parts[6]) if parts[6] else 0,
                            "hopping": parts[7] == "1",
                            "parsers": _unesc(parts[8])},
                           raw=wire)
    except (ValueError, IndexError) as e:
        raise ProtocolError(f"malformed {tag}: {e}") from e
    raise ProtocolError(f"unhandled tag: {tag}")


def _check_min(parts: List[str], n: int) -> None:
    if len(parts) < n:
        raise ProtocolError(f"expected >= {n} fields, got {len(parts)}")
