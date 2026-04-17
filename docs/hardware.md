# Hardware

## Central server

Full-spectrum coverage from a single Pi using wideband SDRs and dedicated network adapters. HackRF's 20 MHz instantaneous bandwidth covers entire bands without hopping. A channelizer extracts narrowband channels from one wideband capture and feeds individual protocol parsers in parallel.

**Minimum hardware for full coverage (7 devices):**

| Device | Center freq | Bandwidth | Modules | Sharing method |
|---|---|---|---|---|
| **HackRF #1** | 440 MHz | 20 MHz | Keyfob, TPMS, PMR, 70cm, ISM 433 | Channelizer → per-protocol parsers |
| **HackRF #2** | 875 MHz | 20 MHz | GSM, LTE, LoRa, ISM 868 | Channelizer → per-protocol parsers |
| **RTL-SDR** | Sweep/hop | 2.4 MHz | ADS-B (1090), AIS (162), Marine VHF, 2m, MURS | Sweep capture or dedicated frequency |
| **BLE adapter** | 2.4 GHz | — | BLE advertisements + drone RemoteID | HCI capture |
| **WiFi adapter** | 2.4/5 GHz | — | Probe requests + drone RemoteID | Monitor mode |
| **Meshtastic radio** | 868 MHz (EU) | — | C2 link to sensor nodes | USB serial (CDC) |
| GPS module | — | — | Position stamp on every detection | USB serial (NMEA) |
| Powered USB hub | — | — | Powers all of the above | USB 3.0 |

### How channelizer sharing works

One HackRF captures 20 MHz of spectrum. The channelizer frequency-shifts, filters, and decimates to extract each protocol's narrowband slice. For example, HackRF #1 at 440 MHz simultaneously feeds:

- 433.92 MHz (2 MHz BW) → keyfob + TPMS parsers
- 446.0 MHz (2 MHz BW) → PMR parser
- 432.0 MHz (2 MHz BW) → 70cm amateur parser

Each parser receives its own baseband IQ stream as if it had a dedicated dongle. The RTL-SDR handles bands outside HackRF antenna range (ADS-B at 1090 MHz, AIS/Marine VHF at 162 MHz) via sweep or dedicated capture.

### HackRF vs RTL-SDR

HackRF has ~10 dB worse sensitivity than RTL-SDR. For strong nearby signals (keyfobs, phones, PMR) this doesn't matter. For weak/distant signals (LoRa, ADS-B), RTL-SDR is better. Use HackRF where bandwidth matters, RTL-SDR where sensitivity matters.

## Sensor node

Target: single-board, battery-powered, ~$80.

| Component | Est. cost | Notes |
|---|---|---|
| Raspberry Pi Zero 2W | ~$15 | Pi 4/5 works too with more headroom |
| RTL-SDR Blog V4 | ~$30 | |
| USB GPS (u-blox 7/8) | ~$15 | NMEA at 9600 baud, `/dev/ttyACM*` |
| Meshtastic radio | ~$20 | See matrix below |
| Battery pack | ~$10 | 10000 mAh gets a full day of scanning |
| Telescopic whip antenna | ~$5 | Tune length to target band |

## Meshtastic radios (for C2)

Any Meshtastic-compatible radio with a USB-CDC serial interface works. Tested during bring-up of this project:

| Radio | HW model | Status | Notes |
|---|---|---|---|
| **Heltec V3** | `HELTEC_V3` | Works | Used as the server radio in the reference setup. CP2102 USB bridge. |
| **RAK4631** | `RAK4631` | Works | Used as agent radios. Good battery behaviour, compact. |
| **LILYGO T-Echo** | `T_ECHO` | Works for RX, TX was unreliable on one unit | Role `CLIENT_MUTE` can still send its own traffic, but we saw a case where the TX chain never reached the server. Swap if suspect. |

All nodes on the C2 mesh must share the same primary channel PSK. Set via `meshtastic --seturl '<URL>'`. The installer scripts (`scripts/install-*.sh`) prompt for this and apply it for you.

## Comms: server ↔ nodes

| Method | Range | Latency | Notes |
|---|---|---|---|
| **LoRa / Meshtastic** | 5–15 km LOS | ~1 s | Default. Tiny CMD/STAT/DET payloads, off-the-shelf mesh, no internet needed. |
| WiFi mesh | ~500 m | <100 ms | Faster but range-limited. Already in the ATAK stack. |

## Power and USB constraints

- **Pi 4 USB budget:** 1.2 A total across all ports. One RTL-SDR (~300 mA) is fine; multiple SDRs need a powered USB hub.
- **HackRF @ 20 MS/s** generates ~40 MB/s per device. Two HackRFs + RTL-SDR + WiFi + BLE = ~85 MB/s total USB throughput — needs USB 3.0 on a Pi 4/5.
- **RTL-SDR retune time:** ~50–100 ms per frequency change. Sets the lower bound for sweep dwell time.

## Antennas

- **40–860 MHz** (5 dBi) — keyfob, TPMS, PMR, 70cm, TETRA, Marine VHF, 2m, ISM 433/868. Best on HackRF #1.
- **700–2700 MHz** (12 dBi) — GSM, LTE, LoRa 868, ADS-B 1090. Best on HackRF #2 or a dedicated RTL-SDR.
- **40 MHz – 6 GHz telescopic** — most versatile; good for an RTL-SDR covering whatever the HackRFs don't.
- Trim telescopic dipole length to the target band for best performance.
