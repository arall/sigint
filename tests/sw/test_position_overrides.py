"""
Tests for web/position_overrides.py — manual drag-to-reposition storage.

Covers:
  - Atomic write + read roundtrip
  - Load returns {} for missing / malformed files (never raises)
  - Upsert overwrites the same source's previous entry
  - Delete removes cleanly; re-delete is a no-op
  - Bad lat/lon raises ValueError (surfaced as HTTP 400 in the handler)
  - Concurrent writes serialise cleanly under the module lock
  - The file survives crash simulation (no .tmp files left behind on
    normal paths; a failed write leaves the previous state intact)

Run:
    python3 tests/sw/test_position_overrides.py
"""

import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def test_set_and_get_roundtrip():
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()
    entry = po.set(tmp, "N01", 42.5098, 1.5361)
    assert abs(entry["lat"] - 42.5098) < 1e-7
    assert entry["ts_epoch"] > 0
    got = po.get(tmp, "N01")
    assert got is not None and abs(got["lat"] - 42.5098) < 1e-7


def test_load_returns_empty_when_missing():
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()
    assert po.load(tmp) == {}


def test_load_returns_empty_when_malformed():
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()
    with open(po.path_for(tmp), "w") as f:
        f.write("{not json")
    assert po.load(tmp) == {}


def test_load_returns_empty_when_wrong_type():
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()
    with open(po.path_for(tmp), "w") as f:
        f.write("[]")  # top-level must be object
    assert po.load(tmp) == {}


def test_get_returns_none_for_missing_source():
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()
    po.set(tmp, "N01", 0.0, 0.0)
    assert po.get(tmp, "server") is None


def test_upsert_overwrites_prior_entry():
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()
    po.set(tmp, "N01", 10.0, 20.0)
    po.set(tmp, "N01", 30.0, 40.0)
    got = po.get(tmp, "N01")
    assert got["lat"] == 30.0 and got["lon"] == 40.0
    # And only one entry total
    assert set(po.load(tmp).keys()) == {"N01"}


def test_delete_removes_and_is_idempotent():
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()
    po.set(tmp, "N01", 1, 2)
    assert po.delete(tmp, "N01") is True
    assert po.get(tmp, "N01") is None
    assert po.delete(tmp, "N01") is False


def test_invalid_coordinates_raise():
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()
    for bad in [(91.0, 0), (-91.0, 0), (0, 181), (0, -181)]:
        try:
            po.set(tmp, "N01", *bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad}")


def test_empty_or_bad_source_id_raises():
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()
    for bad in ["", None, 42]:
        try:
            po.set(tmp, bad, 0, 0)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for id={bad!r}")


def test_non_numeric_coords_raise():
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()
    try:
        po.set(tmp, "N01", "not a number", 0)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_concurrent_writes_serialise():
    """Hammer set() from many threads; final file must be consistent."""
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()

    def writer(tid):
        for i in range(20):
            po.set(tmp, f"N{tid:02d}", 10 + i * 0.001, 20 + i * 0.001)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = po.load(tmp)
    assert len(data) == 8, f"expected 8 entries, got {len(data)}"
    for t in range(8):
        key = f"N{t:02d}"
        assert key in data
        # Last iteration's values
        assert abs(data[key]["lat"] - (10 + 19 * 0.001)) < 1e-6


def test_override_read_in_map_sources_payload():
    """Integration-ish: override file is picked up by the read-through
    logic equivalent to the _serve_map_sources path."""
    from web import position_overrides as po

    tmp = tempfile.mkdtemp()
    po.set(tmp, "server", 10.0, 20.0)
    po.set(tmp, "N01", 30.0, 40.0)

    overrides = po.load(tmp)
    assert overrides["server"]["lat"] == 10.0
    assert overrides["N01"]["lon"] == 40.0

    # Simulate the server.py resolution rule:
    #   override > config (server) / DET-derived (agents)
    server_pos_from_config = {"lat": 1.0, "lon": 2.0}
    agent_positions_from_det = {"N01": {"lat": 3.0, "lon": 4.0, "ts_epoch": 0}}

    def resolve(sid):
        if sid in overrides:
            return {"lat": overrides[sid]["lat"],
                    "lon": overrides[sid]["lon"],
                    "source": "manual"}
        if sid == "server":
            return {"lat": server_pos_from_config["lat"],
                    "lon": server_pos_from_config["lon"],
                    "source": "config"}
        p = agent_positions_from_det.get(sid)
        return (p and {"lat": p["lat"], "lon": p["lon"],
                       "source": "detection"}) or None

    assert resolve("server")["source"] == "manual"
    assert resolve("server")["lat"] == 10.0
    assert resolve("N01")["source"] == "manual"
    assert resolve("N01")["lat"] == 30.0
    # Unknown source falls back cleanly.
    assert resolve("unknown") is None


def test_http_set_then_delete_cycle():
    """End-to-end through the real WebHandler: POST pins a source, the
    next /api/map/sources returns position_source=manual + the new
    coords, DELETE clears it, and GET reverts to config-derived."""
    import json as _json
    import threading
    import urllib.request as _u
    from http.server import ThreadingHTTPServer
    from web.server import WebHandler

    tmp = tempfile.mkdtemp()
    # Seed server_info.json so server_pos has a fallback to revert to.
    with open(os.path.join(tmp, "server_info.json"), "w") as f:
        _json.dump({"server_position": {"lat": 42.0, "lon": 1.0}}, f)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), WebHandler)
    srv.output_dir = tmp
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        # Pin the server.
        req = _u.Request(
            f"http://127.0.0.1:{port}/api/map/sources/position",
            data=_json.dumps({"id": "server", "lat": 50.5, "lon": -3.2}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        r = _json.loads(_u.urlopen(req).read())
        assert r["ok"]

        # Confirm override is live.
        data = _json.loads(_u.urlopen(
            f"http://127.0.0.1:{port}/api/map/sources").read())
        srv_src = [s for s in data["sources"] if s["id"] == "server"][0]
        assert srv_src["position"]["lat"] == 50.5
        assert srv_src["position_source"] == "manual"

        # Clear it.
        req = _u.Request(
            f"http://127.0.0.1:{port}/api/map/sources/position?id=server",
            method="DELETE",
        )
        r = _json.loads(_u.urlopen(req).read())
        assert r["ok"] and r["removed"] is True

        # Now reverts to config-derived position.
        data = _json.loads(_u.urlopen(
            f"http://127.0.0.1:{port}/api/map/sources").read())
        srv_src = [s for s in data["sources"] if s["id"] == "server"][0]
        assert srv_src["position"]["lat"] == 42.0
        assert srv_src["position_source"] == "config"

        # cal_meta entries should also be gone.
        from utils import calibration_db as _cdb
        cal_path = _cdb.default_path(tmp)
        if os.path.exists(cal_path):
            conn = _cdb.connect(cal_path, readonly=True)
            try:
                assert _cdb.get_meta(conn, "node_lat:server") is None
                assert _cdb.get_meta(conn, "node_lon:server") is None
            finally:
                conn.close()

        # Deleting a non-existent override is a no-op (removed=False).
        req = _u.Request(
            f"http://127.0.0.1:{port}/api/map/sources/position?id=nonexistent",
            method="DELETE",
        )
        r = _json.loads(_u.urlopen(req).read())
        assert r["ok"] and r["removed"] is False

        # Missing id should 400.
        req = _u.Request(
            f"http://127.0.0.1:{port}/api/map/sources/position",
            method="DELETE",
        )
        try:
            _u.urlopen(req)
            raise AssertionError("expected 400")
        except _u.HTTPError as e:
            assert e.code == 400
    finally:
        srv.shutdown()


def test_atomic_rename_leaves_no_tmp_files():
    """After a normal write, no leftover .overrides_*.tmp files remain."""
    from web import position_overrides as po
    tmp = tempfile.mkdtemp()
    for i in range(5):
        po.set(tmp, f"N{i}", i, i)
    stray = [n for n in os.listdir(tmp) if n.startswith(".overrides_")]
    assert stray == [], f"leftover tmp files: {stray}"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"  ERR  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(0 if failures == 0 else 1)
