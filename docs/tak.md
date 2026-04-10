# TAK Server Integration

Detections are streamed as CoT (Cursor on Target) events over SSL to a TAK Server, appearing as markers on ATAK maps in real-time. Each detection includes GPS coordinates, signal type, frequency, and SNR.

## Client Certificate Setup

The `signClient` enrollment API may not work on all TAK 5.x deployments. Generate the client certificate directly on the TAK Server instead.

**1. Generate the certificate** — SSH into the TAK Server:

```sh
cd /opt/tak/certs
sudo ./makeCert.sh client sdr-node
```

**2. Register the certificate as a TAK user:**

```sh
cd /opt/tak
sudo java -jar utils/UserManager.jar certmod /opt/tak/certs/files/sdr-node.pem
# Add to a specific group (must match your ATAK devices):
sudo java -jar utils/UserManager.jar certmod -g <group-name> /opt/tak/certs/files/sdr-node.pem
```

**3. Copy files to the project** — from the TAK Server, copy these to `atak/`:

```sh
scp tak-server:/opt/tak/certs/files/sdr-node.p12 atak/
scp tak-server:/opt/tak/certs/files/ca.pem atak/
```

The `.p12` contains the cert + key bundle. On first run with `--tak`, the client auto-extracts `client.pem` and `client.key` from it. The `atak/` directory should contain:

| File | Description |
|------|-------------|
| `ca.pem` | CA certificate (verifies server identity) |
| `sdr-node.p12` | PKCS12 bundle (auto-extracted to client.pem + client.key) |

Connection details are read from `atak/config.pref` if present, otherwise from `TAK_HOST` and `TAK_PORT` environment variables (`.env` file).

## CoT Event Types

| Signal Type | CoT Type | Stale (s) | Description |
|-------------|----------|-----------|-------------|
| PMR446 | `a-n-G-E-S` | 300 | Ground electronic signal |
| keyfob | `a-n-G-E-S` | 60 | Ground electronic signal |
| tpms | `a-n-G-E-V` | 60 | Ground vehicle |
| ADS-B | `a-n-A-C-F` | 60 | Airborne civilian fixed-wing |
| AIS | `a-n-S-X` | 120 | Surface vessel |
| WiFi/BLE | `a-n-G-E-S` | 120 | Ground electronic signal |
| Trails | `u-d-f` | 300 | Drawing shape (polyline) |

## Movement Trails

The `TrailTracker` class in `utils/tak.py` sends CoT polyline shapes for mobile emitters. When a device is seen at 3+ distinct positions with 10+ meters of total movement, a colored trail polyline is sent to ATAK showing where the device has been.

Trail colors: orange (BLE), blue (WiFi), cyan (TPMS), green (keyfob), red (RemoteID drones).

The server hooks this automatically — no configuration needed beyond `--tak --gps`.

## Heatmap Overlay

The `LiveHeatmap` class periodically exports a KML GroundOverlay to the output directory. Load the KML file into ATAK (Import Manager → Local) to see RF activity density as a colored overlay on the map.

For post-hoc analysis, use `python3 sdr.py heatmap output/*.csv` to generate the KML from CSV logs.
