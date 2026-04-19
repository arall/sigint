"""Server-side registry and ingestion for mesh agents."""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Set

from comms import protocol as P
from utils import db as _db
from utils.logger import SignalDetection


# Ring buffer cap for the C2 comms log. ~500 events covers an hour at
# roughly the worst-case ACK + STAT + DET cadence and stays well under
# a megabyte of memory.
_COMMS_LOG_MAX = 500


class AgentManager:
    def __init__(self, link, state_dir: str, detection_db_path: str):
        self._link = link
        self._state_dir = state_dir
        self._db_path = detection_db_path
        os.makedirs(state_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._approved: Dict[str, dict] = {}
        self._pending: Dict[str, dict] = {}
        self._info: Dict[str, dict] = {}
        self._seen_dedup: Dict[str, Set[int]] = {}
        self._comms_log: Deque[dict] = deque(maxlen=_COMMS_LOG_MAX)
        self._load_agents_json()
        self._conn = _db.connect(detection_db_path)
        link.on_message(self._on_msg)

    # -- comms log --------------------------------------------------------

    def _log_comm(self, direction: str, raw: str) -> None:
        """Record a single C2 message for the dashboard's Logs sub-tab.

        `direction` is "tx" (server -> agent) or "rx" (agent -> server).
        Tag and agent_id are extracted from `raw` so the UI can filter
        without re-parsing.

        Deliberately does NOT acquire self._lock — several call sites
        (e.g. _on_det, _on_stat) hit this from inside `with self._lock:`,
        and the lock is non-reentrant. deque.append is atomic in CPython,
        which is sufficient here.
        """
        tag = ""
        agent_id = ""
        try:
            parts = raw.split("|", 3)
            tag = parts[0] if parts else ""
            agent_id = parts[1] if len(parts) > 1 else ""
        except Exception:
            pass
        self._comms_log.append({
            "ts": time.time(),
            "direction": direction,
            "tag": tag,
            "agent_id": agent_id,
            "raw": raw,
        })

    def _send(self, raw: str) -> None:
        """Send a message and record it in the comms log."""
        try:
            self._link.send(raw)
        finally:
            self._log_comm("tx", raw)

    def comms_log(self, limit: int = 200, offset: int = 0) -> tuple:
        """Return a slice of the comms log, newest-first, plus the total."""
        # list() over a deque is atomic snapshot — no lock needed for
        # the reader either. May briefly include or exclude an entry
        # being written, which is fine for a UI poll.
        snapshot = list(self._comms_log)
        snapshot.reverse()
        total = len(snapshot)
        return snapshot[offset:offset + limit], total

    # -- public API -------------------------------------------------------

    def pending(self) -> Dict[str, dict]:
        with self._lock: return dict(self._pending)

    def approved(self) -> Dict[str, dict]:
        with self._lock: return dict(self._approved)

    def agent_info(self, agent_id: str) -> Optional[dict]:
        with self._lock: return dict(self._info.get(agent_id, {}))

    def approve(self, agent_id: str) -> bool:
        with self._lock:
            if agent_id in self._approved:
                return True
            entry = self._pending.pop(agent_id, None)
            if entry is None:
                entry = {"first_seen_at": time.time()}
            entry["approved_at"] = time.time()
            self._approved[agent_id] = entry
            self._save_agents_json_locked()
        self._send(P.encode_approve(agent_id))
        return True

    def revoke(self, agent_id: str) -> None:
        with self._lock:
            self._approved.pop(agent_id, None)
            self._save_agents_json_locked()

    def send_cmd(self, agent_id: str, verb: str, args) -> None:
        self._send(P.encode_cmd(agent_id, verb, list(args or [])))

    def send_cfg(self, agent_id: str, key: str, value: str) -> None:
        self._send(P.encode_cfg(agent_id, key, value))

    # -- dispatch ---------------------------------------------------------

    def _on_msg(self, text: str) -> None:
        self._log_comm("rx", text)
        try:
            msg = P.decode(text)
        except P.ProtocolError:
            return

        if msg.tag == "HELLO":
            self._on_hello(msg.agent_id, msg.fields)
            return

        with self._lock:
            approved = msg.agent_id in self._approved
        if not approved:
            return

        if msg.tag == "DET":
            self._on_det(msg.agent_id, msg.seq, msg.fields)
        elif msg.tag == "STAT":
            self._on_stat(msg.agent_id, msg.seq, msg.fields)
        elif msg.tag == "LOG":
            self._on_log(msg.agent_id, msg.seq, msg.fields)
        elif msg.tag == "RES":
            self._on_res(msg.agent_id, msg.fields)
        elif msg.tag == "CFGINFO":
            self._on_cfginfo(msg.agent_id, msg.seq, msg.fields)
        elif msg.tag == "SCANINFO":
            self._on_scaninfo(msg.agent_id, msg.seq, msg.fields)

    def _on_cfginfo(self, agent_id: str, seq: Optional[int], fields: dict) -> None:
        with self._lock:
            info = self._info.setdefault(agent_id, {})
            info["config"] = {
                "mesh_channel_index": fields.get("mesh_channel_index", 0),
                "meshtastic_port": fields.get("meshtastic_port", ""),
                "gps_port": fields.get("gps_port", ""),
                "state_dir": fields.get("state_dir", ""),
                "version": fields.get("version", ""),
                "hw": fields.get("hw", ""),
                "received_at": time.time(),
            }
        if seq is not None:
            self._send(P.encode_ack(agent_id, seq))

    def _on_scaninfo(self, agent_id: str, seq: Optional[int], fields: dict) -> None:
        with self._lock:
            info = self._info.setdefault(agent_id, {})
            info["scanner_info"] = {
                "scanner_type": fields.get("scanner_type", ""),
                "center_mhz": fields.get("center_mhz", 0.0),
                "bw_mhz": fields.get("bw_mhz", 0.0),
                "channels": fields.get("channels", 0),
                "hopping": fields.get("hopping", False),
                "parsers": fields.get("parsers", ""),
                "received_at": time.time(),
            }
        if seq is not None:
            self._send(P.encode_ack(agent_id, seq))

    def _on_hello(self, agent_id: str, fields: dict) -> None:
        # Agent `_hello_loop` only sends HELLO while `self._state.adopted`
        # is False (src/agent/agent.py:294), so any HELLO from someone we
        # already have in `_approved` is the agent telling us its state.json
        # got wiped — fresh service install, manual cleanup, etc. Re-send
        # APPROVE so it re-adopts without needing `adopted: true` to be
        # hand-edited back in. Idempotent on the agent side.
        resend_approve = False
        with self._lock:
            if agent_id in self._approved:
                self._approved[agent_id]["last_seen_at"] = time.time()
                resend_approve = True
            else:
                entry = self._pending.get(agent_id) or {"first_seen_at": time.time()}
                entry["last_seen_at"] = time.time()
                entry["version"] = fields.get("version", "")
                entry["hw"] = fields.get("hw", "")
                self._pending[agent_id] = entry
        # Send outside the lock: `_send` hits the mesh link which may block.
        if resend_approve:
            self._send(P.encode_approve(agent_id))

    def _on_det(self, agent_id: str, seq: Optional[int], fields: dict) -> None:
        if seq is None:
            return
        with self._lock:
            dedup = self._seen_dedup.setdefault(agent_id, set())
            if seq in dedup:
                self._send(P.encode_ack(agent_id, seq))
                return
            dedup.add(seq)
            if len(dedup) > 50000:
                # trim oldest half — simple cap to keep memory bounded
                self._seen_dedup[agent_id] = set(list(dedup)[-25000:])

        try:
            rssi = float(fields["rssi"])
            snr = fields.get("snr")
            # If the agent sent SNR, reconstruct the noise floor exactly so
            # SignalDetection.create() recomputes the same SNR. If not, fall
            # back to the old assumption of SNR=10.
            noise_floor = rssi - (float(snr) if snr is not None else 10.0)
            det = SignalDetection.create(
                signal_type=fields["type"],
                frequency_hz=float(fields["freq_mhz"]) * 1e6,
                power_db=rssi,
                noise_floor_db=noise_floor,
                channel=fields.get("summary") or None,
                latitude=fields.get("lat"),
                longitude=fields.get("lon"),
                device_id=agent_id,
                metadata=json.dumps({"mesh": True, "seq": seq,
                                      "ts_unix": fields.get("ts_unix")}),
            )
            try:
                ts_unix = int(fields.get("ts_unix") or 0)
                if ts_unix > 0:
                    det.timestamp = datetime.fromtimestamp(ts_unix).isoformat()
                    # Keep ts_epoch in lockstep with timestamp so age filters
                    # and any `WHERE ts_epoch >= ?` queries see the original
                    # detection time, not our ingest time.
                    det.ts_epoch = float(ts_unix)
            except Exception:
                pass
            with self._lock:
                _db.insert_detection(self._conn, det)
                if agent_id in self._approved:
                    self._approved[agent_id]["last_seen_at"] = time.time()
        except Exception as e:
            # Never let a bad payload stall the agent's outbox — log and still ACK
            print(f"[agent {agent_id}] DET seq {seq} insertion failed: {e}")
        self._send(P.encode_ack(agent_id, seq))

    def _on_stat(self, agent_id: str, seq: Optional[int], fields: dict) -> None:
        with self._lock:
            info = self._info.setdefault(agent_id, {})
            info.update({
                "last_seen_at": time.time(),
                "scanner": fields.get("scanner"),
                "state": fields.get("state"),
                "lat": fields.get("lat"),
                "lon": fields.get("lon"),
                "sats": fields.get("sats"),
                "cpu": fields.get("cpu"),
                "uptime_sec": fields.get("uptime_sec"),
            })
            if agent_id in self._approved:
                self._approved[agent_id]["last_seen_at"] = time.time()
        if seq is not None:
            self._send(P.encode_ack(agent_id, seq))

    def _on_log(self, agent_id: str, seq: Optional[int], fields: dict) -> None:
        # best-effort console log on central
        try:
            print(f"[agent {agent_id}] {fields.get('level')}: {fields.get('text')}")
        except Exception:
            pass
        if seq is not None:
            self._send(P.encode_ack(agent_id, seq))

    def _on_res(self, agent_id: str, fields: dict) -> None:
        with self._lock:
            info = self._info.setdefault(agent_id, {})
            info["last_res"] = {
                "verb": fields.get("verb"), "result": fields.get("result"),
                "msg": fields.get("msg"), "at": time.time(),
            }

    # -- persistence ------------------------------------------------------

    def _agents_json_path(self) -> str:
        return os.path.join(self._state_dir, "agents.json")

    def _load_agents_json(self) -> None:
        path = self._agents_json_path()
        try:
            with open(path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        self._approved.update(data.get("approved", {}) or {})

    def _save_agents_json_locked(self) -> None:
        path = self._agents_json_path()
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"approved": self._approved}, f, indent=2)
        os.replace(tmp, path)
