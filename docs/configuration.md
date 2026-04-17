# Configuration

Both the central server and the remote agent take a JSON config file. Examples live in `configs/*.json.example`; customize and save as `configs/server.json` or `configs/agent.json`.

## Server (`configs/server.json`)

Two top-level keys:

```json
{
  "meshlink": { ... },      // optional — enables C2 over Meshtastic
  "captures": [ ... ],      // one entry per capture source
  "web_port": 8080          // optional — starts embedded web UI on this port
}
```

### `meshlink`

Optional. Opens a Meshtastic serial link, attaches an AgentManager, and routes incoming HELLO/STAT/DET messages from agents into `output/agents_YYYYMMDD_HHMMSS.db`.

| Field | Type | Default | Notes |
|---|---|---|---|
| `port` | string | — | Serial path, prefer `/dev/serial/by-id/...` for stability |
| `channel_index` | int | `0` | Meshtastic channel index to transmit on |

### `captures`

Each entry is one capture source. The `type` field selects the backend.

Common fields across all types:

| Field | Type | Notes |
|---|---|---|
| `name` | string | Label for dashboard + logs (e.g. `"pmr"`, `"uhf"`, `"ble"`) |
| `type` | string | One of: `hackrf`, `rtlsdr`, `rtlsdr_sweep`, `ble`, `wifi`, `standalone` |

#### `type: "hackrf"`

Wideband IQ capture fed through a channelizer.

```json
{
  "name": "pmr",
  "type": "hackrf",
  "serial": "0000000000000000a06063c8244f6b5f",
  "ppm": 0,
  "center_freq_mhz": 446.1,
  "sample_rate_mhz": 4,
  "lna_gain": 32,
  "vga_gain": 40,
  "transcribe": false,
  "channels": []
}
```

- `serial` — HackRF serial (from `hackrf_info`); matters only when multiple are attached.
- `center_freq_mhz`, `sample_rate_mhz` — capture center and bandwidth.
- `lna_gain` (0–40, step 8) + `vga_gain` (0–62, step 2) — receive gains.
- `transcribe` — global default; each voice channel can override.
- `channels: []` — if empty, the server auto-discovers FM voice bands that fit within the capture (PMR446, PMR446 Digital, 70cm, etc.). Otherwise, provide explicit entries:

```json
"channels": [
  {
    "name": "keyfob",
    "freq_mhz": 433.92,
    "bandwidth_mhz": 2,
    "parsers": ["keyfob", "tpms"]
  }
]
```

Channel fields: `name`, `freq_mhz`, `bandwidth_mhz`, `parsers` (list of parser names), plus optional `transcribe`, `whisper_model`, `language`.

#### `type: "rtlsdr"`

Fixed-frequency RTL-SDR capture.

```json
{
  "name": "ais",
  "type": "rtlsdr",
  "device_index": 0,
  "center_freq_mhz": 162.0,
  "sample_rate_mhz": 2.4,
  "parsers": ["ais"]
}
```

#### `type: "rtlsdr_sweep"`

RTL-SDR in sweep mode, covering a band by hopping.

```json
{
  "name": "ism",
  "type": "rtlsdr_sweep",
  "device_index": 0,
  "band_start_mhz": 433,
  "band_end_mhz": 435,
  "parsers": ["keyfob", "tpms"]
}
```

#### `type: "ble"`

```json
{
  "name": "ble",
  "type": "ble",
  "adapter": "hci1",
  "parsers": ["apple_continuity", "remoteid_ble"]
}
```

Requires `sudo` (HCI access).

#### `type: "wifi"`

```json
{
  "name": "wifi",
  "type": "wifi",
  "interface": "wlan1",
  "band": "all",
  "parsers": ["probe_request", "beacon", "remoteid_wifi"]
}
```

`band`: `"2.4"`, `"5"`, or `"all"`. Custom channel list via `"channels": [1, 6, 11, 36, 48]`. Requires `sudo` + a monitor-mode capable adapter.

#### `type: "standalone"`

Wrap an existing `sdr.py <subcommand>` as a managed subprocess (stdout drained in the background so the pipe buffer doesn't block). Useful for scanners that aren't yet capture/parser-based.

```json
{
  "name": "adsb",
  "type": "standalone",
  "scanner_type": "adsb",
  "device_index": 0,
  "gain": 40,
  "args": ["--transcribe"]
}
```

### Available parser names

- `fm_voice` (implicit from FM band auto-discovery)
- `keyfob`, `tpms`
- `gsm`, `lte`
- `apple_continuity`, `remoteid_ble`
- `probe_request`, `beacon`, `remoteid_wifi`
- `lora`, `elrs`, `meshtastic`

### Example configs in the repo

- `configs/server.json.example` — HackRF UHF (keyfob/TPMS), HackRF ISM 868 (LoRa/ELRS), ADS-B, BLE, WiFi
- `configs/server_voice.json.example` — adds FM voice demod (PMR + 70cm) via channelizer, with transcription
- `configs/multi_3band.json.example` — three HackRFs covering separate bands
- `configs/hackrf_pmr.json.example` — single HackRF, PMR-only

## Agent (`configs/agent.json`)

Used by `sdr.py agent`. Flat JSON:

```json
{
  "agent_id": "N01",
  "meshtastic_port": "/dev/serial/by-id/usb-RAKwireless_WisCore_RAK4631_Board_XXXX-if00",
  "mesh_channel_index": 0,
  "state_dir": "/var/lib/sigint",
  "gps_port": "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00"
}
```

| Field | Type | Notes |
|---|---|---|
| `agent_id` | string | Short identifier, ideally `N01`…`N99`. Shows up in the Agents tab and as `device_id` on every detection. |
| `meshtastic_port` | string | Serial path to the Meshtastic radio. |
| `mesh_channel_index` | int | Must match the server's `meshlink.channel_index`. Default `0`. |
| `state_dir` | string | Where `state.json`, `outbox.db`, and the scanner's session DB live. `/var/lib/sigint` for systemd installs. |
| `gps_port` | string \| null | NMEA GPS serial (u-blox 7/8). Handed to the scanner subprocess as `--gps --gps-port <path>`. |

Environment-variable overrides (if not set in JSON):

- `SIGINT_AGENT_ID`
- `SIGINT_MESHTASTIC_PORT`

Example: `configs/agent.json.example`.

## Environment file (`.env`)

At project root:

```sh
OPENAI_API_KEY=sk-...
WHISPER_LANGUAGES=en,es
TAK_HOST=tak.example.com
TAK_PORT=8089
```

See `.env.example` for the full list.
