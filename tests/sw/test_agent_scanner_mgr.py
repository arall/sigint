"""Tests for ScannerManager: launch sdr.py subprocess + tail its .db."""
import os
import sys
import tempfile
import time

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def test_manager_starts_and_stops_stub_scanner(tmp_path):
    """Use a stub binary — we just need to verify subprocess lifecycle."""
    from agent.scanner_mgr import ScannerManager

    # A trivial script: sleep, then exit. No real scanner needed for lifecycle test.
    stub = tmp_path / "stub.py"
    stub.write_text("import time\ntime.sleep(10)\n")

    mgr = ScannerManager(
        python_exe=sys.executable,
        sdr_py=str(stub),   # we pass a stub, not the real sdr.py
        output_dir=str(tmp_path),
        device_id="N01",
    )
    mgr.start("ignored", args=[], use_sdr_dispatch=False)
    time.sleep(0.3)
    assert mgr.is_running()
    assert mgr.pid() is not None
    mgr.stop(timeout=2.0)
    assert not mgr.is_running()


def test_tailer_sees_new_rows_in_scanner_db(tmp_path):
    """ScannerManager tails the newest .db and calls the on_detection callback."""
    from agent.scanner_mgr import DBTailer
    from utils.logger import SignalLogger, SignalDetection

    # Write detections to a db that mimics what a scanner would create.
    log = SignalLogger(output_dir=str(tmp_path), signal_type="test",
                      device_id="N01", min_snr_db=0)
    db_path = log.start()

    seen = []
    tailer = DBTailer(db_dir=str(tmp_path), on_row=lambda r: seen.append(r))
    tailer.start()

    log.log(SignalDetection.create(
        signal_type="pmr", frequency_hz=446.00625e6,
        power_db=-60, noise_floor_db=-90, channel="CH1"))
    log.log(SignalDetection.create(
        signal_type="pmr", frequency_hz=446.00625e6,
        power_db=-65, noise_floor_db=-90, channel="CH2"))

    # Wait for the tailer to pick up the rows
    deadline = time.time() + 3.0
    while len(seen) < 2 and time.time() < deadline:
        time.sleep(0.1)

    tailer.stop()
    log.stop()

    assert len(seen) == 2
    types = [r["signal_type"] for r in seen]
    assert types == ["pmr", "pmr"]
    channels = [r["channel"] for r in seen]
    assert channels == ["CH1", "CH2"]


def test_tailer_picks_newest_by_filename_not_mtime(tmp_path):
    """Regression: bumping an older file's mtime above the live one
    must not redirect the tailer. WAL sidecar touches (web dashboard
    read-only opens, background checkpoints) do exactly that in
    production, and the old mtime-based _newest_db would silently
    switch to the dead file and stop forwarding detections."""
    from agent.scanner_mgr import DBTailer

    # Two files with chronologically ordered filenames. Timestamps match
    # SignalLogger's "<signal_type>_YYYYMMDD_HHMMSS.db" convention.
    old_name = tmp_path / "pmr_20260101_000000.db"
    new_name = tmp_path / "pmr_20260419_120000.db"
    old_name.write_bytes(b"")
    new_name.write_bytes(b"")

    # Make the OLDER file look freshly touched — simulates a stale
    # reader / WAL checkpoint bumping its mtime well above the live
    # session's mtime.
    now = time.time()
    os.utime(str(old_name), (now, now + 60))
    os.utime(str(new_name), (now - 3600, now - 3600))

    tailer = DBTailer(db_dir=str(tmp_path), on_row=lambda r: None)
    # The filename-parsed selector must still return the newer file
    # by its embedded timestamp, not the mtime-leading one.
    assert tailer._newest_db() == str(new_name)


def test_tailer_falls_back_to_mtime_for_nonstandard_names(tmp_path):
    """If every file in the dir lacks the SignalLogger timestamp
    pattern, _newest_db falls back to mtime ordering so hand-rolled
    fixtures and unusual dumps keep working. Documented compatibility
    path — don't break tests that wrote bare `cap.db` files."""
    from agent.scanner_mgr import DBTailer

    a = tmp_path / "a.db"
    b = tmp_path / "b.db"
    a.write_bytes(b"")
    b.write_bytes(b"")
    now = time.time()
    os.utime(str(a), (now - 100, now - 100))
    os.utime(str(b), (now, now))

    tailer = DBTailer(db_dir=str(tmp_path), on_row=lambda r: None)
    assert tailer._newest_db() == str(b)
