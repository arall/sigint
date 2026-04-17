#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2; exit 1
fi

cp "$(dirname "$0")/sigint-server.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sigint-server.service
echo "Server installed and started."
echo "Logs: journalctl -u sigint-server -f"
