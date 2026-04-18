"""Agent: wires MeshLink, ScannerManager, Outbox, and AgentState together."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import List, Optional

from comms import protocol as P
from comms.meshlink import MeshLink
from agent.outbox import Outbox
from agent.state import AgentState
from agent.scanner_mgr import ScannerManager


class Agent:
    def __init__(self, state_dir: str, agent_id: str, meshlink: MeshLink,
                 scanner_mgr: Optional[ScannerManager] = None,
                 cfg_snapshot: Optional[dict] = None):
        self._dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        self._state = AgentState.load(os.path.join(state_dir, "state.json"),
                                      default_agent_id=agent_id)
        self._outbox = Outbox(os.path.join(state_dir, "outbox.db"),
                              retry_max_sec=self._state.config["retry_max_sec"])
        self._link = meshlink
        self._scanner_mgr = scanner_mgr
        # Static config snapshot the agent broadcasts in CFGINFO so the
        # dashboard can render an "agent config" view. Built by main.py
        # from configs/agent.json + AgentConfig.
        self._cfg_snapshot = cfg_snapshot or {}
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        # Process start timestamp for the STAT uptime field.
        self._start_ts = time.time()
        # Path the scanner subprocess drops a {lat, lon, sats, ts} sidecar
        # into. Agent polls it for STAT — avoids holding the GPS port
        # concurrently with the scanner.
        self._gps_sidecar = os.path.join(state_dir, "scanner", "gps.json")
        self._link.on_message(self._on_msg)

    # -- public API -------------------------------------------------------

    def start(self, hello_interval: float = 30.0,
              stat_interval: Optional[float] = None,
              drain_interval: Optional[float] = None) -> None:
        self._stop.clear()
        if drain_interval is None:
            drain_interval = float(self._state.config["det_rate_sec"])
        if stat_interval is None:
            stat_interval = float(self._state.config["stat_interval_sec"])

        t1 = threading.Thread(target=self._drainer_loop,
                              args=(drain_interval,), daemon=True)
        t2 = threading.Thread(target=self._stat_loop,
                              args=(stat_interval,), daemon=True)
        t3 = threading.Thread(target=self._hello_loop,
                              args=(hello_interval,), daemon=True)
        for t in (t1, t2, t3):
            t.start()
            self._threads.append(t)

        if self._state.adopted and self._state.current_scanner and self._scanner_mgr:
            cs = self._state.current_scanner
            try:
                self._scanner_mgr.start(cs["type"], cs.get("args", []))
            except Exception:
                pass

        # Fire one CFGINFO at start so the dashboard can render the
        # agent's static config view. AgentManager keeps the latest
        # snapshot in info[agent_id]['config'].
        self._enqueue_cfginfo()
        # And one SCANINFO so the dashboard knows what (if anything)
        # the agent is currently scanning.
        self._enqueue_scaninfo()

    def _enqueue_cfginfo(self) -> None:
        if not self._cfg_snapshot:
            return
        seq = self._outbox.enqueue("CFGINFO", "")
        cfg = self._cfg_snapshot
        payload = P.encode_cfginfo(
            self._state.agent_id, seq,
            mesh_channel_index=int(cfg.get("mesh_channel_index", 0)),
            meshtastic_port=str(cfg.get("meshtastic_port") or ""),
            gps_port=str(cfg.get("gps_port") or ""),
            state_dir=str(cfg.get("state_dir") or ""),
            version=str(cfg.get("version") or "0.1"),
            hw=str(cfg.get("hw") or "rpi"),
        )
        self._outbox.update_payload(seq, payload)

    def _enqueue_scaninfo(self) -> None:
        from agent.scanner_meta import for_scanner
        cs = self._state.current_scanner or {}
        scanner_type = cs.get("type", "")
        if scanner_type:
            meta = for_scanner(scanner_type)
        else:
            meta = {"center_mhz": 0.0, "bw_mhz": 0.0, "channels": 0,
                    "hopping": False, "parsers": ""}
        seq = self._outbox.enqueue("SCANINFO", "")
        payload = P.encode_scaninfo(
            self._state.agent_id, seq,
            scanner_type=scanner_type,
            center_mhz=float(meta["center_mhz"]),
            bw_mhz=float(meta["bw_mhz"]),
            channels=int(meta["channels"]),
            hopping=bool(meta["hopping"]),
            parsers=str(meta["parsers"]),
        )
        self._outbox.update_payload(seq, payload)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads = []
        if self._scanner_mgr and self._scanner_mgr.is_running():
            self._scanner_mgr.stop()
        self._outbox.close()

    def enqueue_det(self, type_: str, freq_mhz: float, rssi: int,
                    lat: Optional[float], lon: Optional[float],
                    ts_unix: int, summary: str = "",
                    snr: Optional[int] = None) -> int:
        seq = self._outbox.enqueue("DET", "")  # seq allocated first
        payload = P.encode_det_truncated(self._state.agent_id, seq, type_,
                                         freq_mhz, rssi, lat, lon, ts_unix,
                                         summary, snr=snr)
        self._outbox.update_payload(seq, payload)
        return seq

    # -- internals --------------------------------------------------------

    def _on_msg(self, text: str) -> None:
        try:
            msg = P.decode(text)
        except P.ProtocolError:
            return

        if msg.tag == "APPROVE" and msg.agent_id == self._state.agent_id:
            self._state.adopted = True
            self._state.save()
            self._link.send(P.encode_res(self._state.agent_id, "APPROVE", "ok"))
            # First adoption — push our config + current scanner snapshot
            # so the server's Agents tab can render them.
            self._enqueue_cfginfo()
            self._enqueue_scaninfo()
            return

        if not self._state.adopted:
            return  # ignore ops traffic before adoption

        if msg.tag == "ACK":
            if msg.agent_id == self._state.agent_id:
                seq = msg.fields["seq"]
                self._outbox.ack(seq)
                if seq > self._state.last_seq_acked:
                    self._state.last_seq_acked = seq
                    self._state.save()
            return

        target = msg.agent_id
        if target not in (self._state.agent_id, "*"):
            return

        if msg.tag == "CMD":
            self._handle_cmd(msg.fields["verb"], msg.fields["args"])
        elif msg.tag == "CFG":
            self._handle_cfg(msg.fields["key"], msg.fields["value"])

    def _handle_cmd(self, verb: str, args: List[str]) -> None:
        ok, res_msg = True, ""
        try:
            if verb == "START":
                if not args:
                    ok, res_msg = False, "missing scanner arg"
                elif self._scanner_mgr is None:
                    ok, res_msg = False, "no scanner_mgr configured"
                else:
                    scanner_type = args[0]
                    tail = args[1:]
                    self._scanner_mgr.start(scanner_type, tail)
                    self._state.current_scanner = {"type": scanner_type, "args": tail}
                    self._state.save()
                    res_msg = f"pid {self._scanner_mgr.pid()}"
                    self._enqueue_scaninfo()
            elif verb == "STOP":
                if self._scanner_mgr:
                    self._scanner_mgr.stop()
                self._state.current_scanner = None
                self._state.save()
                self._enqueue_scaninfo()
            elif verb == "STATUS":
                self._emit_stat()
            elif verb == "SET":
                if len(args) < 2:
                    ok, res_msg = False, "usage: SET <param> <value>"
                # Scanner-specific SET: no-op at Phase 1. Record but don't act.
            else:
                ok, res_msg = False, f"unknown verb {verb}"
        except Exception as e:
            ok, res_msg = False, str(e)[:120]
        self._link.send(P.encode_res(self._state.agent_id, verb,
                                      "ok" if ok else "err", res_msg))

    def _handle_cfg(self, key: str, value: str) -> None:
        if key in self._state.config:
            try:
                self._state.config[key] = int(value)
            except ValueError:
                self._state.config[key] = value
            self._state.save()
            self._link.send(P.encode_res(self._state.agent_id, "CFG", "ok",
                                          f"{key}={value}"))
        else:
            self._link.send(P.encode_res(self._state.agent_id, "CFG", "err",
                                          f"unknown key {key}"))

    # -- loops ------------------------------------------------------------

    def _drainer_loop(self, rate_sec: float) -> None:
        while not self._stop.is_set():
            row = self._outbox.next_due(now=time.time())
            if row is not None and row.payload:
                try:
                    self._link.send(row.payload)
                except Exception:
                    pass
                self._outbox.mark_tried(row.seq, time.time())
                if row.seq > self._state.last_seq_sent:
                    self._state.last_seq_sent = row.seq
                    self._state.save()
                self._stop.wait(rate_sec)
            else:
                self._stop.wait(max(0.5, rate_sec / 2))

    def _stat_loop(self, interval: float) -> None:
        while not self._stop.is_set():
            self._emit_stat()
            self._stop.wait(interval)

    def _emit_stat(self) -> None:
        seq = self._outbox.enqueue("STAT", "")
        scanner = (self._state.current_scanner or {}).get("type", "idle")
        state = "running" if (self._scanner_mgr and self._scanner_mgr.is_running()) else "idle"

        # GPS from the scanner-side sidecar (None if it hasn't been
        # written yet, or the file is older than 60 s).
        lat, lon, sats = None, None, 0
        try:
            st = os.stat(self._gps_sidecar)
            if (time.time() - st.st_mtime) < 60:
                with open(self._gps_sidecar) as f:
                    g = json.load(f)
                lat = g.get("lat")
                lon = g.get("lon")
                sats = int(g.get("sats", 0) or 0)
        except (OSError, ValueError, json.JSONDecodeError):
            pass

        # 1-minute load average normalised to a percentage of total cores.
        cpu = 0
        try:
            ncpu = os.cpu_count() or 1
            cpu = int(round((os.getloadavg()[0] / ncpu) * 100))
        except (OSError, AttributeError):
            pass

        uptime_sec = int(time.time() - self._start_ts)

        payload = P.encode_stat(self._state.agent_id, seq, scanner, state,
                                 lat=lat, lon=lon, sats=sats, cpu=cpu,
                                 uptime_sec=uptime_sec)
        self._outbox.update_payload(seq, payload)

    def _hello_loop(self, interval: float) -> None:
        while not self._stop.is_set():
            if not self._state.adopted:
                try:
                    self._link.send(P.encode_hello(self._state.agent_id, "0.1", "rpi0"))
                except Exception:
                    pass
            self._stop.wait(interval)
