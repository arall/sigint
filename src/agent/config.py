"""agent.conf loader (INI-style, very small)."""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from typing import Optional


DEFAULT_CONF_PATH = "/etc/sigint/agent.conf"


@dataclass
class AgentConfig:
    agent_id: str
    meshtastic_port: Optional[str]
    mesh_channel_index: int = 0
    state_dir: str = "/var/lib/sigint"
    gps_port: Optional[str] = None

    @classmethod
    def load(cls, path: str = DEFAULT_CONF_PATH) -> "AgentConfig":
        cp = configparser.ConfigParser()
        cp.read_dict({"agent": {}})
        if os.path.exists(path):
            cp.read(path)
        sec = cp["agent"] if "agent" in cp else {}
        agent_id = sec.get("agent_id") or os.environ.get("SIGINT_AGENT_ID", "N00")
        port = sec.get("meshtastic_port") or os.environ.get("SIGINT_MESHTASTIC_PORT")
        return cls(
            agent_id=agent_id,
            meshtastic_port=port,
            mesh_channel_index=int(sec.get("mesh_channel_index", 0)),
            state_dir=sec.get("state_dir", "/var/lib/sigint"),
            gps_port=sec.get("gps_port"),
        )
