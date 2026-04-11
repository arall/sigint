"""
RF Activity Heatmap Generator

Generates spatial density heatmaps from detection logs.
Output: KML GroundOverlay with PNG tile for ATAK map display.

Usage:
    from utils.heatmap import HeatmapGenerator
    gen = HeatmapGenerator()
    gen.add_detection(lat, lon, power_db)
    gen.export_kml("output/heatmap.kml")

    # Or from a detection DB:
    gen = HeatmapGenerator.from_db("output/server_20250101_120000.db")
    gen.export_kml("output/heatmap.kml")
"""

import math
import os
import struct
import zlib
from collections import defaultdict
from datetime import datetime
from typing import List, Optional, Tuple

from utils import db as _db


# Grid resolution (degrees) — ~100m at mid-latitudes
DEFAULT_GRID_RESOLUTION = 0.001

# Minimum detections in a cell to render
MIN_CELL_COUNT = 1

# Color gradient: blue → cyan → green → yellow → red (low → high activity)
HEATMAP_COLORS = [
    (0, 0, 255, 100),    # blue (low)
    (0, 200, 255, 130),  # cyan
    (0, 255, 100, 160),  # green
    (255, 255, 0, 180),  # yellow
    (255, 100, 0, 200),  # orange
    (255, 0, 0, 220),    # red (high)
]


def _interpolate_color(value: float) -> Tuple[int, int, int, int]:
    """Map a 0.0-1.0 value to an RGBA color along the gradient."""
    value = max(0.0, min(1.0, value))
    n = len(HEATMAP_COLORS) - 1
    idx = value * n
    lo = int(idx)
    hi = min(lo + 1, n)
    frac = idx - lo

    r = int(HEATMAP_COLORS[lo][0] + frac * (HEATMAP_COLORS[hi][0] - HEATMAP_COLORS[lo][0]))
    g = int(HEATMAP_COLORS[lo][1] + frac * (HEATMAP_COLORS[hi][1] - HEATMAP_COLORS[lo][1]))
    b = int(HEATMAP_COLORS[lo][2] + frac * (HEATMAP_COLORS[hi][2] - HEATMAP_COLORS[lo][2]))
    a = int(HEATMAP_COLORS[lo][3] + frac * (HEATMAP_COLORS[hi][3] - HEATMAP_COLORS[lo][3]))
    return r, g, b, a


def _write_png(pixels: list, width: int, height: int, path: str):
    """Write an RGBA PNG file without matplotlib/PIL dependency.

    Uses raw zlib + PNG chunk encoding — minimal but correct.
    """
    def _chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    # IHDR
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA

    # IDAT — row-filtered pixel data
    raw = b''
    for y in range(height):
        raw += b'\x00'  # filter: None
        for x in range(width):
            r, g, b, a = pixels[y * width + x]
            raw += struct.pack('BBBB', r, g, b, a)

    signature = b'\x89PNG\r\n\x1a\n'
    with open(path, 'wb') as f:
        f.write(signature)
        f.write(_chunk(b'IHDR', ihdr))
        f.write(_chunk(b'IDAT', zlib.compress(raw)))
        f.write(_chunk(b'IEND', b''))


class HeatmapGenerator:
    """Accumulates detections and generates spatial heatmaps."""

    def __init__(self, resolution: float = DEFAULT_GRID_RESOLUTION,
                 signal_types: Optional[List[str]] = None):
        """
        Args:
            resolution: Grid cell size in degrees (~111m per 0.001 deg)
            signal_types: Filter to specific signal types (None = all)
        """
        self.resolution = resolution
        self.signal_types = set(signal_types) if signal_types else None
        # grid[(lat_bin, lon_bin)] → {"count": N, "total_power": sum, "max_power": max}
        self._grid = defaultdict(lambda: {"count": 0, "total_power": 0.0, "max_power": -999.0})
        self._bounds = None  # (min_lat, min_lon, max_lat, max_lon)

    def _bin(self, lat: float, lon: float) -> Tuple[int, int]:
        """Convert lat/lon to grid cell index."""
        return (int(math.floor(lat / self.resolution)),
                int(math.floor(lon / self.resolution)))

    def add_detection(self, lat: float, lon: float, power_db: float = 0.0,
                      signal_type: str = ""):
        """Add a single detection to the heatmap grid."""
        if lat is None or lon is None:
            return
        if lat == 0.0 and lon == 0.0:
            return  # Skip null-island detections
        if self.signal_types and signal_type not in self.signal_types:
            return

        key = self._bin(lat, lon)
        cell = self._grid[key]
        cell["count"] += 1
        cell["total_power"] += power_db
        cell["max_power"] = max(cell["max_power"], power_db)

        # Update bounds
        if self._bounds is None:
            self._bounds = [lat, lon, lat, lon]
        else:
            self._bounds[0] = min(self._bounds[0], lat)
            self._bounds[1] = min(self._bounds[1], lon)
            self._bounds[2] = max(self._bounds[2], lat)
            self._bounds[3] = max(self._bounds[3], lon)

    @classmethod
    def from_db(cls, db_path: str, resolution: float = DEFAULT_GRID_RESOLUTION,
                signal_types: Optional[List[str]] = None) -> "HeatmapGenerator":
        """Load detections from a .db log file."""
        gen = cls(resolution=resolution, signal_types=signal_types)
        conn = _db.connect(db_path, readonly=True)
        try:
            for r in _db.iter_detections(conn):
                lat = r["latitude"]
                lon = r["longitude"]
                if lat is None or lon is None:
                    continue
                try:
                    gen.add_detection(
                        float(lat), float(lon),
                        float(r["power_db"] or 0),
                        r["signal_type"] or "",
                    )
                except (ValueError, TypeError):
                    continue
        finally:
            conn.close()
        return gen

    @property
    def bounds(self) -> Optional[Tuple[float, float, float, float]]:
        """Return (min_lat, min_lon, max_lat, max_lon) or None if empty."""
        return tuple(self._bounds) if self._bounds else None

    @property
    def cell_count(self) -> int:
        return len(self._grid)

    @property
    def total_detections(self) -> int:
        return sum(c["count"] for c in self._grid.values())

    def render_png(self, path: str, max_pixels: int = 512) -> Optional[Tuple[float, float, float, float]]:
        """Render heatmap to PNG. Returns bounds (south, west, north, east) or None."""
        if not self._grid or not self._bounds:
            return None

        min_lat, min_lon, max_lat, max_lon = self._bounds

        # Add padding (one cell each side)
        pad = self.resolution
        min_lat -= pad
        min_lon -= pad
        max_lat += pad
        max_lon += pad

        # Grid dimensions
        lat_cells = int(math.ceil((max_lat - min_lat) / self.resolution))
        lon_cells = int(math.ceil((max_lon - min_lon) / self.resolution))

        if lat_cells < 1 or lon_cells < 1:
            return None

        # Scale to max_pixels
        scale = 1
        if max(lat_cells, lon_cells) > max_pixels:
            scale = max_pixels / max(lat_cells, lon_cells)
            width = max(1, int(lon_cells * scale))
            height = max(1, int(lat_cells * scale))
        else:
            width = lon_cells
            height = lat_cells

        # Find count range for normalization
        counts = [c["count"] for c in self._grid.values() if c["count"] >= MIN_CELL_COUNT]
        if not counts:
            return None
        max_count = max(counts)
        # Use log scale for better dynamic range
        log_max = math.log1p(max_count)

        # Build pixel array (top = north, so iterate lat from max to min)
        pixels = [(0, 0, 0, 0)] * (width * height)  # transparent background
        for (lat_bin, lon_bin), cell in self._grid.items():
            if cell["count"] < MIN_CELL_COUNT:
                continue

            # Map grid cell to pixel
            cell_lat = lat_bin * self.resolution
            cell_lon = lon_bin * self.resolution
            px = int((cell_lon - min_lon) / self.resolution * (width / lon_cells))
            py = int((max_lat - cell_lat - self.resolution) / self.resolution * (height / lat_cells))

            if 0 <= px < width and 0 <= py < height:
                value = math.log1p(cell["count"]) / log_max if log_max > 0 else 0
                pixels[py * width + px] = _interpolate_color(value)

        _write_png(pixels, width, height, path)
        return (min_lat, min_lon, max_lat, max_lon)

    def export_kml(self, kml_path: str, png_path: str = None,
                   name: str = "RF Activity Heatmap"):
        """Export heatmap as KML with embedded PNG GroundOverlay.

        Args:
            kml_path: Output KML file path
            png_path: PNG file path (default: same dir as KML, .png extension)
            name: Overlay name shown in ATAK
        """
        if png_path is None:
            png_path = os.path.splitext(kml_path)[0] + ".png"

        bounds = self.render_png(png_path)
        if bounds is None:
            print("[heatmap] No data with GPS coordinates — skipping export")
            return None

        south, west, north, east = bounds
        png_basename = os.path.basename(png_path)
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{name}</name>
    <description>Generated {now} — {self.total_detections} detections in {self.cell_count} cells</description>
    <GroundOverlay>
      <name>{name}</name>
      <Icon>
        <href>{png_basename}</href>
      </Icon>
      <LatLonBox>
        <north>{north:.8f}</north>
        <south>{south:.8f}</south>
        <east>{east:.8f}</east>
        <west>{west:.8f}</west>
      </LatLonBox>
    </GroundOverlay>
  </Document>
</kml>"""

        with open(kml_path, 'w') as f:
            f.write(kml)

        print(f"[heatmap] Exported: {kml_path} ({self.total_detections} detections, "
              f"{self.cell_count} cells)")
        return kml_path


class LiveHeatmap:
    """Real-time heatmap that accumulates detections and periodically exports.

    Designed to be called from ServerOrchestrator._on_detection.
    """

    def __init__(self, output_dir: str, interval_s: float = 60.0,
                 resolution: float = DEFAULT_GRID_RESOLUTION,
                 signal_types: Optional[List[str]] = None):
        self._generator = HeatmapGenerator(
            resolution=resolution, signal_types=signal_types)
        self._output_dir = output_dir
        self._interval_s = interval_s
        self._last_export = 0.0
        self._detection_count = 0
        self._export_count = 0

    def on_detection(self, detection):
        """Feed a SignalDetection into the live heatmap."""
        self._generator.add_detection(
            detection.latitude, detection.longitude,
            detection.power_db, detection.signal_type,
        )
        self._detection_count += 1

        # Periodic export
        import time
        now = time.time()
        if now - self._last_export >= self._interval_s and self._generator.cell_count > 0:
            self._export()
            self._last_export = now

    def _export(self):
        """Export current heatmap state."""
        kml_path = os.path.join(self._output_dir, "heatmap.kml")
        self._generator.export_kml(kml_path)
        self._export_count += 1

    def flush(self):
        """Force an export (call on shutdown)."""
        if self._generator.cell_count > 0:
            self._export()
