#!/bin/sh
# Writes the node's primary IPv4 + agent_id to a known location each
# time NetworkManager raises an interface, and prints to the system
# console. Useful in the field to find a node's address without
# scanning the subnet:
#
#   - SSH in via any other route (Ethernet, USB-net, lab WiFi, the
#     iPhone hotspot), then `cat /var/lib/sigint/net.txt`.
#   - Plug a HDMI monitor into the Pi during boot — the line is
#     echoed to `/dev/console` so you'll see it on the splash screen.
#   - The same value is broadcast over Meshtastic in the agent's
#     CFGINFO message, so the central dashboard shows it under the
#     agent's "Config" panel.
#
# Install:
#   sudo cp scripts/print-ip.sh /usr/local/sbin/sigint-print-ip
#   sudo chmod +x /usr/local/sbin/sigint-print-ip
#   sudo ln -sf /usr/local/sbin/sigint-print-ip \
#     /etc/NetworkManager/dispatcher.d/99-sigint-print-ip
#
# Then NetworkManager fires it on every up/down event. State persists
# in /var/lib/sigint/net.txt across reboots so you can pull the last
# known IP even when the link is currently down.

set -eu

OUT=/var/lib/sigint/net.txt
mkdir -p "$(dirname "$OUT")"

agent_id=$(grep -o '"agent_id"[^,}]*' /home/arall/code/sigint/configs/agent.json 2>/dev/null \
    | sed 's/.*"\([^"]*\)"$/\1/' || echo "?")
ip=$(ip route get 1.1.1.1 2>/dev/null | awk '/src/ {for (i=1;i<=NF;i++) if ($i=="src") print $(i+1); exit}')
ip="${ip:-(none)}"

line="$(date -Iseconds) $agent_id $ip"
echo "$line" > "$OUT"
echo "[sigint] $line" > /dev/console 2>/dev/null || true
