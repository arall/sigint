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

**6. Agent in the middle of the chain is `CLIENT_MUTE`.** A `CLIENT_MUTE` node sends its own traffic but won't repeat anything else, so a node that has to reach the server through it never gets through. Set every relay-capable agent radio to `CLIENT`:

```sh
venv/bin/meshtastic --port /dev/serial/by-id/usb-<radio>-if00 --set device.role CLIENT
```

See [c2.md → Mesh relay between agents](c2.md#mesh-relay-between-agents) for details.

## `sdr.py agent` / `server` dies immediately

```sh
journalctl -u sigint-agent -n 50 --no-pager
```

Most common:

- **`FileNotFoundError: configs/*.json`** — config path in the unit doesn't resolve. Check `WorkingDirectory=` and `ExecStart=` in `/etc/systemd/system/sigint-*.service`. Should have the real project dir, not `@PROJECT_DIR@`.
- **`ERROR: meshtastic_port not configured`** — empty `"meshtastic_port"` in `configs/agent.json`.
- **`[Errno 11] Could not exclusively lock port ...`** — another process (an older ad-hoc `sdr.py`, a stale `meshtastic` CLI, `minicom`, …) holds the serial port. `sudo fuser /dev/ttyUSB0` to find it.

## State-sync drift (agent ignores commands)

Resolved — the server now auto-re-approves on HELLO from an already-approved agent. The agent's `_hello_loop` only beacons while `adopted=false`, so a HELLO arriving for someone in `agents.json` is unambiguous: the agent's `state.json` got wiped (fresh service install, manual cleanup, …) and the server fires a fresh `APPROVE`. No hand-editing needed.

If the agent still isn't adopting after a HELLO, check the C2 Logs sub-tab on the Agents page for the APPROVE frame. Common causes: hop-limit too small for the deployment, or the agent radio is in `CLIENT_MUTE` mode (see [c2.md — Mesh relay between agents](c2.md#mesh-relay-between-agents)).

## BT / WiFi scanners over mesh: don't

This isn't a bug — it's a **physics limit of LoRa**, worth documenting so operators don't chase a software fix that can't exist.

### Symptom
- Agent's `outbox.db` keeps growing even though detections look small.
- Server sees only a fraction of what the agent's local scanner DB contains.
- Dashboard's "Recent detections from agents" page lags by tens of minutes.

### Why (the physics)
EU 868 MHz LoRa is regulated to ~**1% duty cycle** — the radio can legally transmit for ~1 second in any 100-second window. With Meshtastic's default LongFast settings, that works out to roughly **one frame every 6 seconds** of throughput. A single phone in range produces 50+ BLE advertisements + WiFi probe requests in that same 6 seconds. Net flow: enqueue rate is ~50× drain rate. The outbox grows monotonically.

There is no software trick that closes this gap:

- **Batch coalescing** (packing N observations into one frame) helps maybe 5–10×. Still not 50×.
- **Per-persona dedup** (drop repeat advertisements) would close the gap, but at the cost of losing the per-advertisement RSSI samples that triangulation, movement detection, and AirTag-stalking analysis all depend on. The whole point of repeat observations is that they *are* information.
- **Sample-rate throttling** drops frames unpredictably — same loss, worse distribution.

### What to do
**Don't run `bt` or `wifi` continuously on a mesh agent.** They belong on the server (full bandwidth to its own SQLite) or on an agent with an alternate link (see roadmap: out-of-band high-rate transport). The mesh agent is right-sized for scanners that emit ~1 detection every several seconds: **PMR voice, keyfob, TPMS, ISM, LoRa, ADS-B, AIS** all fit comfortably in the duty-cycle budget.

For post-hoc analysis of a mesh-only deployment that captured BT/WiFi locally: pull the agent's `state_dir/scanner/*.db` over SSH / USB and feed it into `sdr.py tri` / `heatmap` / `correlate` alongside the server's files. The tools already union across per-node `.db`s, so an out-of-band file pull joins cleanly with the live-streamed data.

If the outbox is already saturated, recover with:

```sh
sudo systemctl stop sigint-agent
sqlite3 /var/lib/sigint/outbox.db 'DELETE FROM outbox WHERE acked=0'
sudo systemctl start sigint-agent
```

## CMD lost in flight

Resolved — server-side `ServerOutbox` now tracks every CMD / CFG by allocated seq and retries with exponential backoff (6 s → 120 s, 5 tries max) until the agent ACKs. Operator clicks Start once.

If the button still appears to do nothing after ~30 s, check the Agents **C2 Logs** sub-tab for the CMD frame (sent) and the subsequent ACK (expected). No ACK usually means the deployment is deeper than `lora.hop_limit` — see [c2.md — Mesh relay between agents](c2.md#mesh-relay-between-agents).

## HackRF queue drops (`degraded` status)

Server shows `[DEGRADED] pmr: dropped N blocks (sample rate too high?)`. The HackRF 4-block queue dropped samples — usually CPU-bound on a Pi when running many parallel captures or transcription.

- Reduce `sample_rate_mhz` in the capture config.
- Disable transcription (`"transcribe": false`) or run only in `whisper_model: "tiny"`.
- Move transcription to a beefier box or use the OpenAI API (`OPENAI_API_KEY` in `.env`).

Each drop marks the capture `degraded` for the web UI; detection continues.

## RTL-SDR `usb_claim_interface error -6`

Another process has the SDR. Two cases:

**Userspace conflict.** `rtl_test`, a running `sdr.py pmr`, `readsb`, or `rtl_ais` — only one can talk to each dongle at a time. `pgrep -af 'rtl_|sdr.py'` and kill the stray.

**Kernel DVB driver.** On a fresh Pi the kernel auto-claims the dongle as a DVB-T tuner. `dmesg` shows `dvb_usb_rtl28xxu` events, `lsmod` lists `rtl2832_sdr` / `dvb_usb_rtl28xxu`. Blacklist + unload — see [install.md → Blacklist the kernel DVB driver](install.md#blacklist-the-kernel-dvb-driver).

## RTL-SDR Blog V4: 0 detections, channel powers stuck at noise floor

### Symptoms
- PMR scanner (or any `pyrtlsdr`-based scanner) starts cleanly, prints `RTL-SDR Blog V4 Detected`, but every channel reads the same value (~20 dB) regardless of TX
- `Gain: 0.0 dB` in scanner startup output even though `--gain 40` was passed
- A direct `rtl_test -t` shows the full V4 gain table (29 values up to 49.6 dB), but `python3 -c "from rtlsdr import RtlSdr; s=RtlSdr(0); s.set_manual_gain_enabled(True); s.gain=40.2; print(s.gain)"` returns `0.0`

### Why
`pyrtlsdr`'s `gain` setter calls `rtlsdr_set_tuner_gain()` (via ctypes). On the V4's R828D tuner the call returns success (rc=0) but the hardware silently ignores it — gain stays at the V4's hardware default. `rtlsdr_set_tuner_gain_ext()` has the same outcome. We tested this against a fresh `rtlsdr_open()` bypassing pyrtlsdr's `RtlSdr` class entirely, same result.

The C tools (`rtl_sdr`, `rtl_power`) program the V4 correctly. So the workaround is to acquire IQ via the CLI rather than via pyrtlsdr.

### Fix
`scanners/pmr.py` ships an `_RtlSdrSubprocess` shim (enabled by default via the `PMR_USE_RTL_SDR_CLI=1` env var) that spawns `rtl_sdr -d N -f F -s R -g G -` and pipes the raw u8 IQ into the same processing path. Set `PMR_USE_RTL_SDR_CLI=0` to fall back to pyrtlsdr if you have hardware where pyrtlsdr's gain works.

If you write a new scanner, copy this pattern — the bug affects every pyrtlsdr-based capture path on the V4, not just PMR.

### Don't drop LD_LIBRARY_PATH for the rtl_sdr subprocess
The locally-built `rtl_sdr` binary requires the V4-fork lib at runtime (it calls `rtlsdr_set_and_get_tuner_bandwidth`, which Debian's 2.0.1 lib doesn't export). The pmr.py shim enforces `LD_LIBRARY_PATH=/usr/local/lib` for the subprocess. If you're spinning up your own ad-hoc test, wrap with `env LD_LIBRARY_PATH=/usr/local/lib rtl_sdr ...`, or you'll hit `undefined symbol: rtlsdr_set_and_get_tuner_bandwidth`.

## Scanner runs but its main loop never displays / never logs detections

### Symptom
- Scanner subprocess at >100% CPU (one core saturated)
- `[dbg] processing chunk #1` appears in the log; chunk #2 never does
- `pmr-direct.log` gets ~10 lines and stops
- `py-spy dump --pid <scanner-pid>` shows the main thread permanently in `calculate_power_spectrum` / `np.blackman` / `_process_all_channels`

### Why
On a Pi 4, a 256K-pt complex FFT takes ~150–300 ms; `rtl_sdr` at 2.4 MS/s emits a chunk every ~110 ms. The scanner's "drain queued chunks" inner loop (`while not sample_queue.empty()`) can't keep up — but the reader thread keeps refilling the bounded queue faster than the consumer drains it, so the inner `empty()` check never returns True. Display + detection logging starve forever.

### Fix
`pmr.py`'s drain loop is now capped to `display_interval` (200 ms): it processes chunks until the deadline, then exits to update the display + run any pending detections. If you copy the pmr.py async pattern into a new scanner, keep the deadline cap.

## Server refuses to start: "Conflicting processes detected"

The server's pre-flight checks for any process holding `hci0` (BLE), the RTL-SDR, or HackRF before starting its own captures. False-positive sources we've seen:

- A leftover standalone `sdr.py bt`, `sdr.py pmr`, `hcitool`, or `hcidump` from an earlier debugging session
- A background polling shell whose **command line** literally contains `sdr.py` (e.g. `until ssh ... 'ps -ef | grep sdr.py'; do sleep 5; done`) — the pre-flight regex matches these too

`sudo pkill -9 -f 'hcitool|hcidump'`, kill any stray `sdr.py` polling loops, then `systemctl restart sigint-server`. The error message lists the exact PIDs.

## "Failed to import scanner module: ..."

The `sdr.py` dispatch imports every scanner's module up-front, so any one missing dep fails all scanners — even ones that don't use the missing package.

- `No module named 'numpy'` / `'scipy'` / `'rtlsdr'` → `venv/bin/pip install -r requirements.txt`
- `Error loading librtlsdr` → install librtlsdr V4 fork (see [install.md](install.md))
- `librtlsdr.so: undefined symbol: rtlsdr_set_dithering` → Debian librtlsdr is being loaded; rebuild the V4 fork or set `LD_LIBRARY_PATH=/usr/local/lib`
- `The scipy install you are using seems to be broken` → partial download; reinstall: `sudo venv/bin/pip install --force-reinstall --no-deps --resume-retries 5 scipy`

## "Could not open port ... [Errno 5] Input/output error" (Heltec / meshtastic)

The Heltec Tracker's USB-serial bridge sometimes wedges, especially after a power loss or a long session. `meshtastic.stream_interface` can't open the port; the agent's watchdog catches it (via `_rxThread.is_alive()`) and exits with code 2 so systemd restarts. If the wedge is at the firmware level rather than the host driver, the restart loops indefinitely.

Recovery:

1. Physically unplug + replug the Heltec USB cable on the affected node.
2. Confirm the device re-enumerates: `dmesg | tail -10` should show a fresh `cdc_acm` event.
3. The systemd `Restart=always` will pick it up at the next iteration.

If the symptom recurs frequently on one specific Heltec unit, the device-side USB chip is flaky — swap to a different radio.

## USB cable enumerates as power-only

When a fresh SDR or radio refuses to enumerate (`lsusb` shows the hub but not the device, no `dmesg` event on plug), check the cable before assuming the SDR is dead. Many short USB cables ship with the data lines unconnected (charge-only). Swap with a known-good data cable.

## Triangulation: dashboard shows no triangulations even though agents are forwarding DETs

### Likely causes (in order)

**1. Correlation window too tight for mesh latency.** The mesh's `det_rate_sec=6` plus LoRa airtime makes "the same emission heard at N nodes" land at the server 6–15 s apart. If `triangulate_live.py:DEFAULT_CORRELATION_WINDOW_S` is set tighter than that, the same emission ends up in different correlation buckets and you only get per-node singletons. We default to **30 s** for this reason.

**2. Forwarded DETs missing GPS coordinates.** A DET without lat/lon is invisible to triangulation — `_shape_detection` filters it out. Two cases:

- The scanner subprocess never writes GPS into its local DB (it has no `--gps` and isn't reading any sidecar). Fix: make sure the agent writes the meshtastic-GPS sidecar, and that `agent/main.py:_on_scanner_row` falls back to that sidecar when `row.latitude is None`. Both are in `main` — check yours hasn't drifted.
- The scanner has GPS but the receiver-end (server) loses it. Inspect the agent's `outbox.db`: `SELECT payload FROM outbox WHERE kind='DET' LIMIT 5` — the wire format is `DET|node|seq|type|freq|rssi|lat|lon|...`; lat/lon should be populated.

**3. BLE-Adv: every device collapses to one trilat group.** Older `apple_continuity.py` set `channel="BLE"` for all detections. The DET wire format only carries one freeform field (`summary`) which becomes the server-side `channel`; trilat's `metadata_id` strategy falls back to that field. Result: every BLE device ends up in one giant correlation bucket and the trilat is meaningless. Fix shipped: parser now sets `channel=mac` so per-device correlation works. Verify with: `SELECT DISTINCT channel FROM detections WHERE signal_type='BLE-Adv' LIMIT 10` — should be MAC-shaped, not the literal string `"BLE"`.

**4. Server's own captures lack a position.** The server has no GPS — its lat/lon is configured in `server.json` as `server_position`. If your version of `triangulate_live.py` doesn't inject this for non-agent rows, server-side detections are dropped from the trilat input. Workaround: run captures via the agent flow (so they go through the GPS-injection path) or patch `_shape_detection` to fall back to `server_position`.

## Server's PMR HackRF capture: "running" but 0 detections

Server's PMR HackRF reports `running` but logs zero detections regardless of how strong the signal is.

- **HackRF unplugged after server start.** `hackrf_transfer` is alive as a child process but the device went away — SIGINT and SIGTERM don't propagate cleanly, and the parent server doesn't notice for ~60 s. Symptom: `hackrf_info` reports a different device count than what's in `output/server_info.json`. Fix: `systemctl restart sigint-server` after replugging.
- **HackRF queue 1-block drop at startup.** Server marks the capture `degraded`. Often the capture continues fine after the initial drop. If it actually stops producing samples after the drop, the FM voice parser thread sees no input and the dashboard sits at "waiting for detections..." — restart the server and watch the first 30 s of `journalctl -u sigint-server`.

## Pi 0 W2 specifically

Pi 0 W2 is slow (single core ARM Cortex-A53) and easily under-powered:

- Agent + scanner startup takes 30–60 s, not the ~10 s of a Pi 4. Don't conclude the agent is wedged just because no scanner has spawned 20 s after restart — wait at least a minute.
- `pip install scipy` is fragile over slow connections. Use `--resume-retries 5`. A partial install will produce `The scipy install you are using seems to be broken` at runtime.
- USB power budget is tight. Bus-powered SDR + meshtastic radio on the same hub can brown out. `vcgencmd get_throttled` should return `0x0`; non-zero means under-voltage was detected at some point. Use a powered hub if you see this.

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
