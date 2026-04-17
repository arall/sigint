"""Agent: wires MeshLink, ScannerManager, Outbox, and AgentState together."""
from __future__ import annotations

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
                 scanner_mgr: Optional[ScannerManager] = None):
        self._dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        self._state = AgentState.load(os.path.join(state_dir, "state.json"),
                                      default_agent_id=agent_id)
        self._outbox = Outbox(os.path.join(state_dir, "outbox.db"),
                              retry_max_sec=self._state.config["retry_max_sec"])
        self._link = meshlink
        self._scanner_mgr = scanner_mgr
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
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
            elif verb == "STOP":
                if self._scanner_mgr:
                    self._scanner_mgr.stop()
                self._state.current_scanner = None
                self._state.save()
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
        payload = P.encode_stat(self._state.agent_id, seq, scanner, state,
                                 lat=None, lon=None, sats=0, cpu=0,
                                 uptime_sec=int(time.time()))
        self._outbox.update_payload(seq, payload)

    def _hello_loop(self, interval: float) -> None:
        while not self._stop.is_set():
            if not self._state.adopted:
                try:
                    self._link.send(P.encode_hello(self._state.agent_id, "0.1", "rpi0"))
                except Exception:
                    pass
            self._stop.wait(interval)
