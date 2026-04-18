#!/usr/bin/env bash
# Install nexmon-patched brcmfmac firmware so the Pi's built-in WiFi
# can do monitor mode + frame injection.
#
# Tested on:
#   - Raspberry Pi 4B (chip bcm43455c0, firmware version 7_45_206)
# Planned:
#   - Raspberry Pi Zero 2 W (chip bcm43436b0, firmware 9_88_4_65)
#
# What this does:
#   1. Installs build deps (gcc-arm-none-eabi, kernel headers, ...).
#   2. Clones seemoo-lab/nexmon into /opt/nexmon (idempotent).
#   3. Builds the patched firmware for the detected chip.
#   4. Backs up the stock firmware once (skip if backup already exists).
#   5. Installs the patched firmware + nexutil tool.
#   6. Reloads the brcmfmac driver.
#   7. Verifies monitor mode works on wlan0.
#
# Safe to re-run. Survives reboots. Doesn't break normal WiFi
# connectivity — wlan0 still works as a STA when not in monitor mode.

set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2; exit 1
fi

MODEL=$(tr -d '\0' < /proc/device-tree/model)
echo "[+] Detected: $MODEL"

case "$MODEL" in
  *"Raspberry Pi 4"*)
    CHIP="bcm43455c0"
    FW_VER="7_45_206"
    ;;
  *"Raspberry Pi Zero 2"*)
    CHIP="bcm43436b0"
    FW_VER="9_88_4_65"
    ;;
  *)
    echo "[!] Unsupported Pi model: $MODEL" >&2
    echo "    Supported: Raspberry Pi 4, Raspberry Pi Zero 2 W" >&2
    exit 1
    ;;
esac

KVER="$(uname -r)"
NEXMON_DIR="/opt/nexmon"
PATCH_DIR="${NEXMON_DIR}/patches/${CHIP}/${FW_VER}/nexmon"
FW_DIR="/lib/firmware/brcm"

echo "[+] Chip: $CHIP, firmware version: $FW_VER, kernel: $KVER"

echo "[+] Installing build deps..."
apt-get update -qq
apt-get install -y --no-install-recommends \
  git build-essential gawk qpdf bison flex libfl-dev make autoconf libtool \
  texinfo curl bc libgmp3-dev libssl-dev gcc-arm-none-eabi \
  iw wireless-tools

# Kernel headers — package name varies across Pi OS revisions.
# Try a few in order; bail only if the headers dir is genuinely missing.
HEADERS_DIR="/usr/src/linux-headers-${KVER}"
if [[ ! -d "$HEADERS_DIR" ]]; then
  for pkg in "linux-headers-${KVER}" linux-headers-rpi-v8 raspberrypi-kernel-headers; do
    if apt-get install -y --no-install-recommends "$pkg" 2>/dev/null; then
      echo "[+] Installed $pkg"
      break
    fi
  done
fi
if [[ ! -d "$HEADERS_DIR" ]]; then
  echo "[!] Kernel headers for $KVER not available." >&2
  echo "    Looked under $HEADERS_DIR." >&2
  exit 1
fi
echo "[+] Kernel headers present at $HEADERS_DIR"

if [[ ! -d "$NEXMON_DIR" ]]; then
  echo "[+] Cloning nexmon into $NEXMON_DIR..."
  git clone --depth 1 https://github.com/seemoo-lab/nexmon.git "$NEXMON_DIR"
else
  echo "[+] nexmon already cloned at $NEXMON_DIR; skipping clone"
fi

if [[ ! -d "$PATCH_DIR" ]]; then
  echo "[!] Patch dir $PATCH_DIR not found in nexmon checkout." >&2
  echo "    Available patches:" >&2
  find "${NEXMON_DIR}/patches/${CHIP}" -maxdepth 1 -mindepth 1 -type d 2>/dev/null >&2 || true
  exit 1
fi

cd "$NEXMON_DIR"

# nexmon needs to build its bundled libisl + libmpfr if the system
# versions don't match. setup_env.sh handles this and exports the
# right paths.
echo "[+] Sourcing nexmon environment..."
# shellcheck disable=SC1091
source ./setup_env.sh

echo "[+] Building nexmon buildtools (isl + mpfr + flashpatch + ucode)..."
# The top-level Makefile runs each buildtool's ./configure + make in turn,
# then extracts ucode/flashpatches from stock firmware. Required before
# building any chip patch.
make

echo "[+] Building patched firmware for $CHIP..."
cd "$PATCH_DIR"
make

# Backup original firmware exactly once
ORIG_BIN="${FW_DIR}/brcmfmac43455-sdio.bin"
BACKUP_BIN="${FW_DIR}/brcmfmac43455-sdio.bin.orig"
if [[ -f "$ORIG_BIN" && ! -f "$BACKUP_BIN" ]]; then
  echo "[+] Backing up stock firmware -> ${BACKUP_BIN}"
  cp "$ORIG_BIN" "$BACKUP_BIN"
fi

echo "[+] Installing patched firmware..."
make backup-firmware || true   # idempotent — uses make logic to backup if needed
make install-firmware

echo "[+] Building + installing nexutil..."
cd "${NEXMON_DIR}/utilities/nexutil"
make
make install

echo "[+] Reloading brcmfmac driver..."
modprobe -r brcmfmac brcmutil 2>/dev/null || true
modprobe brcmutil
modprobe brcmfmac
sleep 3

echo "[+] Verifying monitor mode on wlan0..."
ip link set wlan0 down
iw dev wlan0 set monitor none
ip link set wlan0 up
iw dev wlan0 info
echo
echo "[OK] If you see 'type monitor' above, nexmon is working."
echo
echo "    To put wlan0 back into normal STA mode:"
echo "      sudo ip link set wlan0 down"
echo "      sudo iw dev wlan0 set type managed"
echo "      sudo ip link set wlan0 up"
echo "      sudo systemctl restart NetworkManager  # or wpa_supplicant"
