"""Server-side registry and ingestion for mesh agents."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from typing import Dict, Optional, Set

from comms import protocol as P
from utils import db as _db
from utils.logger import SignalDetection


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
        self._load_agents_json()
        self._conn = _db.connect(detection_db_path)
        link.on_message(self._on_msg)

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
        self._link.send(P.encode_approve(agent_id))
        return True

    def revoke(self, agent_id: str) -> None:
        with self._lock:
            self._approved.pop(agent_id, None)
            self._save_agents_json_locked()

    def send_cmd(self, agent_id: str, verb: str, args) -> None:
        self._link.send(P.encode_cmd(agent_id, verb, list(args or [])))

    def send_cfg(self, agent_id: str, key: str, value: str) -> None:
        self._link.send(P.encode_cfg(agent_id, key, value))

    # -- dispatch ---------------------------------------------------------

    def _on_msg(self, text: str) -> None:
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

    def _on_hello(self, agent_id: str, fields: dict) -> None:
        with self._lock:
            if agent_id in self._approved:
                self._approved[agent_id]["last_seen_at"] = time.time()
                return
            entry = self._pending.get(agent_id) or {"first_seen_at": time.time()}
            entry["last_seen_at"] = time.time()
            entry["version"] = fields.get("version", "")
            entry["hw"] = fields.get("hw", "")
            self._pending[agent_id] = entry

    def _on_det(self, agent_id: str, seq: Optional[int], fields: dict) -> None:
        if seq is None:
            return
        with self._lock:
            dedup = self._seen_dedup.setdefault(agent_id, set())
            if seq in dedup:
                self._link.send(P.encode_ack(agent_id, seq))
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
            except Exception:
                pass
            with self._lock:
                _db.insert_detection(self._conn, det)
                if agent_id in self._approved:
                    self._approved[agent_id]["last_seen_at"] = time.time()
        except Exception as e:
            # Never let a bad payload stall the agent's outbox — log and still ACK
            print(f"[agent {agent_id}] DET seq {seq} insertion failed: {e}")
        self._link.send(P.encode_ack(agent_id, seq))

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
            self._link.send(P.encode_ack(agent_id, seq))

    def _on_log(self, agent_id: str, seq: Optional[int], fields: dict) -> None:
        # best-effort console log on central
        try:
            print(f"[agent {agent_id}] {fields.get('level')}: {fields.get('text')}")
        except Exception:
            pass
        if seq is not None:
            self._link.send(P.encode_ack(agent_id, seq))

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
