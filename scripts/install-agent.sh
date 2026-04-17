#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2; exit 1
fi

read -rp "Agent ID (e.g. N01): " AGENT_ID
: "${AGENT_ID:?required}"

read -rp "Meshtastic serial port [/dev/ttyACM0]: " MESH_PORT
MESH_PORT="${MESH_PORT:-/dev/ttyACM0}"

read -rp "GPS serial port (optional): " GPS_PORT

mkdir -p /etc/sigint /var/lib/sigint
cat > /etc/sigint/agent.conf <<EOF
[agent]
agent_id = ${AGENT_ID}
meshtastic_port = ${MESH_PORT}
mesh_channel_index = 0
state_dir = /var/lib/sigint
gps_port = ${GPS_PORT}
EOF

cp "$(dirname "$0")/sigint-agent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sigint-agent.service
echo "Agent ${AGENT_ID} installed and started."
echo "Logs: journalctl -u sigint-agent -f"
