#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2; exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONF="${PROJECT_DIR}/configs/server.json"

if [[ -e "${CONF}" ]]; then
  read -rp "configs/server.json already exists. Overwrite? [y/N]: " OVERWRITE
  [[ "${OVERWRITE,,}" == "y" ]] || SKIP_CONFIG=1
fi

if [[ -z "${SKIP_CONFIG:-}" ]]; then
  echo
  echo "Available example configs:"
  EXAMPLES=()
  for f in "${PROJECT_DIR}"/configs/*.json.example; do
    [[ "$(basename "${f}")" == "agent.json.example" ]] && continue
    EXAMPLES+=("${f}")
  done
  PS3="Pick a template (or enter 0 to skip and write configs/server.json by hand later): "
  select EX in "${EXAMPLES[@]}" "none (skip)"; do
    if [[ "${REPLY}" == "0" || "${EX}" == "none (skip)" ]]; then
      echo "Skipping config copy. You must write ${CONF} before starting the service."
      SKIP_CONFIG=1
      break
    elif [[ -n "${EX}" && -f "${EX}" ]]; then
      cp "${EX}" "${CONF}"
      echo "Copied $(basename "${EX}") -> $(basename "${CONF}"). Edit ${CONF} to set HackRF serials, ports, etc."
      break
    fi
  done
fi

read -rp "Meshtastic serial port (optional, press Enter to skip): " MESH_PORT
if [[ -n "${MESH_PORT}" ]]; then
  read -rp "Meshtastic channel URL (optional, press Enter to keep current radio config): " MESH_URL
  if [[ -n "${MESH_URL}" ]]; then
    echo "Applying channel URL to radio on ${MESH_PORT}..."
    "${PROJECT_DIR}/venv/bin/meshtastic" --port "${MESH_PORT}" --seturl "${MESH_URL}"
  fi
fi

if [[ -z "${SKIP_CONFIG:-}" && ! -f "${CONF}" ]]; then
  echo "ERROR: ${CONF} missing — service would fail to start. Aborting." >&2
  exit 1
fi

cp "$(dirname "$0")/sigint-server.service" /etc/systemd/system/
systemctl daemon-reload
if [[ -f "${CONF}" ]]; then
  systemctl enable --now sigint-server.service
  echo "Server installed and started."
else
  systemctl enable sigint-server.service
  echo "Server unit installed but not started (no ${CONF})."
  echo "Write the config and run: sudo systemctl start sigint-server.service"
fi
echo "Logs: journalctl -u sigint-server -f"
