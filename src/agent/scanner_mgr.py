"""ScannerManager: runs a `sdr.py <scanner>` subprocess on the remote node and
tails its SQLite output so the Agent can forward each new detection.
"""
from __future__ import annotations

import glob
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, List, Optional


class ScannerManager:
    def __init__(self, python_exe: str, sdr_py: str, output_dir: str,
                 device_id: str, gps_port: Optional[str] = None):
        self._python = python_exe
        self._sdr_py = sdr_py
        self._output_dir = output_dir
        self._device_id = device_id
        self._gps_port = gps_port
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._drain_threads: List[threading.Thread] = []

    def start(self, scanner_type: str, args: Optional[List[str]] = None,
              use_sdr_dispatch: bool = True) -> int:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                raise RuntimeError("scanner already running")
            os.makedirs(self._output_dir, exist_ok=True)

            if use_sdr_dispatch:
                cmd = [self._python, self._sdr_py,
                       "--output", self._output_dir,
                       "--device-id", self._device_id]
                if self._gps_port:
                    cmd += ["--gps", "--gps-port", self._gps_port]
                cmd.append(scanner_type)
                if args:
                    cmd.extend(args)
            else:
                # Test / stub mode: just run the script with no framework wrapping
                cmd = [self._python, self._sdr_py] + (args or [])

            self._proc = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(os.path.abspath(self._sdr_py)) or ".",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            self._drain_threads = [
                threading.Thread(target=self._drain, args=(self._proc.stdout,),
                                 daemon=True),
                threading.Thread(target=self._drain, args=(self._proc.stderr,),
                                 daemon=True),
            ]
            for t in self._drain_threads:
                t.start()
            return self._proc.pid

    def _drain(self, stream):
        try:
            for _ in iter(lambda: stream.read(4096), b""):
                pass
        except Exception:
            pass

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def pid(self) -> Optional[int]:
        with self._lock:
            return self._proc.pid if self._proc else None

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            if not self._proc:
                return
            if self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
                try:
                    self._proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                    self._proc.wait()
            self._proc = None


class DBTailer:
    """Tails the newest .db in output_dir, invoking on_row for each new row."""
    def __init__(self, db_dir: str, on_row: Callable[[dict], None],
                 poll_interval: float = 0.5):
        self._dir = db_dir
        self._on_row = on_row
        self._poll = poll_interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_rowid = 0
        self._tracked_db: Optional[str] = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _newest_db(self) -> Optional[str]:
        candidates = glob.glob(os.path.join(self._dir, "*.db"))
        if not candidates:
            return None
        return max(candidates, key=os.path.getmtime)

    def _loop(self) -> None:
        from utils import db as _db
        while not self._stop.is_set():
            newest = self._newest_db()
            if newest is None:
                time.sleep(self._poll)
                continue
            if newest != self._tracked_db:
                self._tracked_db = newest
                self._last_rowid = 0
            try:
                conn = _db.connect(newest, readonly=True)
            except Exception:
                time.sleep(self._poll)
                continue
            try:
                rows = conn.execute(
                    "SELECT * FROM detections WHERE id > ? ORDER BY id",
                    (self._last_rowid,),
                ).fetchall()
                for r in rows:
                    self._last_rowid = int(r["id"])
                    self._on_row(dict(r))
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
            time.sleep(self._poll)
