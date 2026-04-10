# Hardware

## Central Server

Full spectrum coverage from a Raspberry Pi with 2x HackRF + 1x RTL-SDR + WiFi/BLE adapters. HackRF's 20 MHz instantaneous bandwidth covers entire bands without hopping. A channelizer layer extracts narrowband channels from wideband captures and feeds individual protocol parsers simultaneously.

**Minimum hardware for full coverage (7 devices):**

| Device | Center Freq | Bandwidth | Modules | Sharing method |
|--------|-------------|-----------|---------|----------------|
| **HackRF #1** | 440 MHz | 20 MHz | Keyfob, TPMS, PMR, 70cm, ISM 433 | Channelizer → per-protocol parsers |
| **HackRF #2** | 875 MHz | 20 MHz | GSM, LTE, LoRa, ISM 868 | Channelizer → per-protocol parsers |
| **RTL-SDR** | Sweep/hop | 2.4 MHz | ADS-B (1090), AIS (162), Marine VHF, 2m, MURS | Sweep capture or dedicated |
| **BLE adapter** | 2.4 GHz | — | BLE devices + drone RemoteID | HCI capture |
| **WiFi adapter** | 2.4 GHz | — | WiFi probes + drone RemoteID | Monitor mode |
| GPS module | — | — | Position for all detections | Serial |
| Powered USB hub | — | — | Powers all devices | USB 3.0 |

**How sharing works:** One HackRF captures 20 MHz of spectrum. The channelizer frequency-shifts, filters, and decimates to extract each protocol's narrowband slice. For example, HackRF #1 at 440 MHz simultaneously feeds:
- 433.92 MHz (2 MHz BW) → keyfob + TPMS parsers
- 446.0 MHz (2 MHz BW) → PMR parser
- 432.0 MHz (2 MHz BW) → 70cm amateur parser

Each parser receives its own baseband IQ stream as if it had a dedicated dongle. The RTL-SDR handles bands outside HackRF antenna range (ADS-B at 1090 MHz, AIS/Marine VHF at 162 MHz) via sweep capture.

**HackRF vs RTL-SDR:** HackRF has ~10 dB worse sensitivity than RTL-SDR. For strong nearby signals (keyfobs, phones, PMR) this doesn't matter. For weak/distant signals (LoRa, ADS-B), RTL-SDR is better. Use HackRF where bandwidth matters, RTL-SDR where sensitivity matters.

## Sensor Node (~$80/unit)

| Component | Est. Cost |
|-----------|-----------|
| Raspberry Pi Zero 2W | ~$15 |
| RTL-SDR Blog V4 | ~$30 |
| USB GPS (u-blox) | ~$15 |
| Meshtastic LoRa module | ~$20 |
| Battery pack | ~$10 |
| Small whip antenna | ~$5 |

## Comms: Server ↔ Nodes

| Method | Range | Latency | Notes |
|--------|-------|---------|-------|
| **LoRa / Meshtastic** | 5-15 km | ~1s | Best fit. Task commands are tiny (~50 bytes). Off-the-shelf mesh. |
| WiFi mesh (ATAK) | ~500m | <100ms | Already in stack, but range-limited |

## Power and USB Constraints

- **Pi 4 USB power budget**: 1.2A total across all USB ports. One RTL-SDR (~300 mA) is fine; multiple SDRs need a powered USB hub.
- **HackRF at 20 MS/s** generates ~40 MB/s per device. Two HackRFs + RTL-SDR + WiFi + BLE = ~85 MB/s total USB throughput.
- **RTL-SDR retune time**: ~50-100 ms per frequency change. Sets the lower bound for sweep dwell time.

## Antennas

- **40-860 MHz** (5 dBi): Covers keyfob, TPMS, PMR, 70cm, TETRA, Marine VHF, 2m, ISM 433/868. Best for HackRF #1.
- **700-2700 MHz** (12 dBi): Covers GSM, LTE, LoRa 868, ADS-B 1090. Best for HackRF #2 or RTL-SDR.
- **40 MHz-6 GHz telescopic**: Most versatile. Good for RTL-SDR covering whatever the HackRFs don't.
- Trim telescopic dipole element length to target band for best performance.
