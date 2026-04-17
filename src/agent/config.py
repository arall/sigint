"""agent.json loader."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional


DEFAULT_CONF_PATH = "configs/agent.json"


@dataclass
class AgentConfig:
    agent_id: str
    meshtastic_port: Optional[str]
    mesh_channel_index: int = 0
    state_dir: str = "/var/lib/sigint"
    gps_port: Optional[str] = None

    @classmethod
    def load(cls, path: str = DEFAULT_CONF_PATH) -> "AgentConfig":
        data: dict = {}
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
        return cls(
            agent_id=data.get("agent_id") or os.environ.get("SIGINT_AGENT_ID", "N00"),
            meshtastic_port=data.get("meshtastic_port") or os.environ.get("SIGINT_MESHTASTIC_PORT"),
            mesh_channel_index=int(data.get("mesh_channel_index", 0)),
            state_dir=data.get("state_dir", "/var/lib/sigint"),
            gps_port=data.get("gps_port"),
        )
