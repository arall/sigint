# Troubleshooting

Common failure modes and fixes, in rough order of how often they bite during bring-up.

## Meshtastic C2 — nothing happens

### Symptoms
- Agent is running, server is running, but the **Agents** tab stays empty.
- `/tmp/sigint-agent.log` shows `[meshlink TX] 'HELLO|...'` but the server never logs the HELLO.

### Things to check, in order

**1. PSK / channel URL mismatch.** Default Meshtastic firmware is on the public LongFast channel with a null PSK. If one radio is on `sigint-c2` (or whatever you called it) and the other is on default, packets fly OTA but neither side can decrypt.

```sh
venv/bin/meshtastic --port /dev/serial/by-id/usb-<radio>-if00 --info | grep -A1 "Complete URL"
```

URLs must match **byte for byte** on both server and agent. Apply with:

```sh
venv/bin/meshtastic --port /dev/serial/by-id/usb-<radio>-if00 --seturl '<URL>'
```

**2. `channel_index` mismatch.** Server's `configs/server.json` has `"meshlink": {"channel_index": N}`; agent's `configs/agent.json` has `"mesh_channel_index": N`. Both must be `0` (or both the same).

**3. LoRa region mismatch.** Radios on different regions (`EU_868` vs `US_915`) physically transmit at different frequencies. Verify in `--info` under `lora.region`.

**4. Radio stuck in debug-text mode.** Sometimes a Meshtastic radio emits ANSI-coloured debug logs on the serial port instead of protobuf frames. The meshtastic-python library's handshake doesn't recover from this reliably in all versions. Force a reboot:

```sh
venv/bin/meshtastic --port /dev/serial/by-id/usb-<radio>-if00 --reboot
```

Wait ~20 s, then restart the service. If it happens again, swap the radio — one specific hardware unit may be flaky.

**5. Actual RF range issue.** Check each radio's `--info` → `Nodes in mesh`. If each side can see the other with a recent `lastHeard` and an SNR > 0, RF is fine. If not, move them closer, check the antenna is seated, or flip a client's role from `CLIENT_MUTE` to `CLIENT` temporarily to diagnose.

## `sdr.py agent` / `server` dies immediately

```sh
journalctl -u sigint-agent -n 50 --no-pager
```

Most common:

- **`FileNotFoundError: configs/*.json`** — config path in the unit doesn't resolve. Check `WorkingDirectory=` and `ExecStart=` in `/etc/systemd/system/sigint-*.service`. Should have the real project dir, not `@PROJECT_DIR@`.
- **`ERROR: meshtastic_port not configured`** — empty `"meshtastic_port"` in `configs/agent.json`.
- **`[Errno 11] Could not exclusively lock port ...`** — another process (an older ad-hoc `sdr.py`, a stale `meshtastic` CLI, `minicom`, …) holds the serial port. `sudo fuser /dev/ttyUSB0` to find it.

## State-sync drift (agent ignores commands)

### Symptom
- Server's **Agents** tab says N01 is approved.
- You click Start → nothing happens. Agent keeps sending `STAT` but never responds to `CMD`.

### Why
The agent's `state.json` says `"adopted": false`. On the server side, `output/agents_state/agents.json` says `N01` is already in `approved`, so the server doesn't re-send `APPROVE`. Deadlock.

### Fix
Either edit the agent state directly:

```sh
sudo sed -i 's/"adopted": false/"adopted": true/' /var/lib/sigint/state.json
sudo systemctl restart sigint-agent
```

Or revoke server-side (edit `output/agents_state/agents.json`, remove the entry under `"approved"`, restart the server, re-approve from the UI).

## CMD lost in flight

Meshtastic text packets are best-effort. A single `CMD START` can be dropped. The web UI doesn't auto-retry. If a click doesn't elicit a `RES|...|ok` within ~10 s, click again. Programmatic callers typically send 2–3 times back-to-back.

## HackRF queue drops (`degraded` status)

Server shows `[DEGRADED] pmr: dropped N blocks (sample rate too high?)`. The HackRF 4-block queue dropped samples — usually CPU-bound on a Pi when running many parallel captures or transcription.

- Reduce `sample_rate_mhz` in the capture config.
- Disable transcription (`"transcribe": false`) or run only in `whisper_model: "tiny"`.
- Move transcription to a beefier box or use the OpenAI API (`OPENAI_API_KEY` in `.env`).

Each drop marks the capture `degraded` for the web UI; detection continues.

## RTL-SDR `usb_claim_interface error -6`

Another process has the SDR. `rtl_test`, a running `sdr.py pmr`, `readsb`, or `rtl_ais` — only one can talk to each dongle at a time. `pgrep -af rtl_|sdr.py` and kill the stray.

## `readsb` finds no aircraft

The Debian `readsb` package is built without RTL-SDR support. You need the source build:

```sh
git clone https://github.com/wiedehopf/readsb.git /tmp/readsb-src
cd /tmp/readsb-src && make -j4 RTLSDR=yes
sudo cp readsb /usr/bin/readsb
```

See [install.md](install.md).

## PMR audio assigned to the wrong channel

RTL-SDR Blog V4 has ~16 ppm oscillator offset — at 446 MHz that's ~7 kHz, enough to shift a transmission into the adjacent 12.5 kHz channel grid. The audio is still captured correctly; only the channel label is wrong. Calibrate with `--ppm <N>` if you care, or use HackRF (~17 ppm but the channelizer absorbs it).

## RF loopback audio quality is bad

Expected. Consumer SDRs hit ~0.25 cross-correlation ceiling on RF loopback because of phase noise. Synthetic (no SDR) loopback reaches 0.83. Don't use RF loopback as a regression test for audio quality.

## Triangulation result is way off

- **Path-loss parameters are uncalibrated.** Room-level accuracy at best with the defaults. See [triangulation.md](triangulation.md) to calibrate.
- **All nodes must use the same gain**, or pass `--use-snr` so the solver normalises.
- **2-node solution is ambiguous** — it has two mirror solutions. Always prefer 3+ nodes in a triangle, not a line.
- **`power_db` is dBFS, not dBm.** Only use absolute values within one capture session.

## BLE / WiFi adapter stops responding between runs

```sh
sudo hciconfig hci1 down
sudo hciconfig hci1 up
# or for WiFi:
sudo ip link set wlan1 down
sudo iw wlan1 set type monitor
sudo ip link set wlan1 up
```

## Dashboard shows stale status

Every category and device view queries SQL directly, so staleness is usually:

- **`server_info.json` not refreshed** — it's only written on capture status transitions. If nothing fails, nothing updates. Not a real bug; just means "still running".
- **Agent STAT interval is 60 s** — the `scanner=idle/running` state in the Agents tab updates at that cadence, not instantly after a CMD. Wait for the next STAT.

## The pypubsub "silent unsubscribe" class of bugs

pypubsub 4.x uses weak references for listeners. When the listener is a **bound method of a nested closure class**, the reference can be lost prematurely and the subscription dies silently — no error, no crash, just nothing delivered.

This project's `src/comms/meshlink.py` avoids it by using a module-level listener + a process-global backend registry. If you ever find yourself adding a new pubsub listener in a similar context and it mysteriously never fires, check this first.

## Where to look next

- `journalctl -u sigint-server -f` / `journalctl -u sigint-agent -f`
- `output/server_console.log` — stdout from the server's parser threads
- `output/server_info.json` — capture status snapshot
- `/var/lib/sigint/state.json` and `/var/lib/sigint/outbox.db` on the agent side
