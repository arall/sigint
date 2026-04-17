#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2; exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONF="${PROJECT_DIR}/configs/agent.json"

read -rp "Agent ID (e.g. N01): " AGENT_ID
: "${AGENT_ID:?required}"

read -rp "Meshtastic serial port [/dev/ttyACM0]: " MESH_PORT
MESH_PORT="${MESH_PORT:-/dev/ttyACM0}"

read -rp "Meshtastic channel URL (optional, press Enter to keep current radio config): " MESH_URL

read -rp "GPS serial port (optional, press Enter to skip): " GPS_PORT

if [[ -n "${MESH_URL}" ]]; then
  echo "Applying channel URL to radio on ${MESH_PORT}..."
  "${PROJECT_DIR}/venv/bin/meshtastic" --port "${MESH_PORT}" --seturl "${MESH_URL}"
fi

mkdir -p "${PROJECT_DIR}/configs" /var/lib/sigint

if [[ -n "${GPS_PORT}" ]]; then
  GPS_JSON="\"${GPS_PORT}\""
else
  GPS_JSON="null"
fi

cat > "${CONF}" <<EOF
{
  "agent_id": "${AGENT_ID}",
  "meshtastic_port": "${MESH_PORT}",
  "mesh_channel_index": 0,
  "state_dir": "/var/lib/sigint",
  "gps_port": ${GPS_JSON}
}
EOF

cp "$(dirname "$0")/sigint-agent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sigint-agent.service
echo "Agent ${AGENT_ID} installed, config at ${CONF}."
echo "Logs: journalctl -u sigint-agent -f"
