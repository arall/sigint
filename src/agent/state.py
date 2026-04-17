"""Agent runtime state persisted to state.json (atomic writes)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional, Any


DEFAULT_CONFIG = {
    "det_rate_sec": 6,
    "stat_interval_sec": 60,
    "retry_max_sec": 900,
    "queue_warn_depth": 1000,
}


@dataclass
class AgentState:
    path: str
    agent_id: str
    adopted: bool = False
    current_scanner: Optional[Dict[str, Any]] = None  # {"type": ..., "args": [...]}
    config: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_CONFIG))
    last_seq_sent: int = 0
    last_seq_acked: int = 0

    @classmethod
    def load(cls, path: str, default_agent_id: str) -> "AgentState":
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}

        cfg = dict(DEFAULT_CONFIG)
        cfg.update(data.get("config", {}) or {})
        return cls(
            path=path,
            agent_id=data.get("agent_id", default_agent_id),
            adopted=bool(data.get("adopted", False)),
            current_scanner=data.get("current_scanner"),
            config=cfg,
            last_seq_sent=int(data.get("last_seq_sent", 0)),
            last_seq_acked=int(data.get("last_seq_acked", 0)),
        )

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        payload = {
            "agent_id": self.agent_id,
            "adopted": self.adopted,
            "current_scanner": self.current_scanner,
            "config": self.config,
            "last_seq_sent": self.last_seq_sent,
            "last_seq_acked": self.last_seq_acked,
        }
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, self.path)
