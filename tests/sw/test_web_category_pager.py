"""
Tests for the server-side category pager.

Exercises `/api/cat/<name>` end-to-end through a real WebHandler +
ThreadingHTTPServer so the offset / limit / filter query parameters,
filter-value enumeration, and wire-shape contract are all verified
together.

Covers:
  - offset + limit slice the full loader output server-side
  - total reflects the post-filter dataset size
  - out-of-range offset is clamped to the last page
  - filters_available enumerates distinct types/channels from the
    full (un-filtered) dataset
  - ?type=<x> filters the page without shrinking filters_available
  - ?audio=1 + ?transcript=1 filters voice rows
  - Omitting offset/limit keeps backward-compatible defaults

Run:
    python3 tests/sw/test_web_category_pager.py
"""

import json
import os
import sys
import tempfile
import threading
import urllib.parse
import urllib.request

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _seed_voice_session(output_dir, count=200):
    """Write `count` voice-ish detections across two channels, alternating
    with/without audio + transcripts so the filter combinations all have
    hits."""
    from utils import db as _db
    from utils.logger import SignalDetection
    path = os.path.join(output_dir, "pmr_20260419_120000.db")
    conn = _db.connect(path)
    for i in range(count):
        audio = f"pmr_ch{(i % 2) + 1}_{i}.wav" if (i % 3 == 0) else None
        det = SignalDetection.create(
            signal_type="PMR446",
            frequency_hz=446.00625e6,
            power_db=-60, noise_floor_db=-90,
            channel=f"CH{(i % 2) + 1}",
            audio_file=audio,
        )
        rowid = _db.insert_detection(conn, det)
        # Whisper transcripts join by audio_file basename; seed a few so
        # ?transcript=1 has something to return.
        if audio and (i % 9 == 0):
            _db.insert_transcript(conn, audio, f"hello {i}", "en")
    conn.close()
    return path


def _start_server(output_dir):
    from http.server import ThreadingHTTPServer
    from web.server import WebHandler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), WebHandler)
    srv.output_dir = output_dir
    srv.tailer = None
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port


def _get_cat(port, name, **params):
    qs = urllib.parse.urlencode(params)
    url = f"http://127.0.0.1:{port}/api/cat/{name}?{qs}"
    return json.loads(urllib.request.urlopen(url).read())


def test_offset_and_limit_slice_server_side():
    tmp = tempfile.mkdtemp()
    _seed_voice_session(tmp, count=200)
    srv, port = _start_server(tmp)
    try:
        page1 = _get_cat(port, "voice", offset=0, limit=50)
        page2 = _get_cat(port, "voice", offset=50, limit=50)
        assert page1["offset"] == 0
        assert page1["limit"] == 50
        assert len(page1["rows"]) == 50
        assert page1["total"] >= 50
        assert page2["offset"] == 50
        assert len(page2["rows"]) == 50
        # No overlap between pages — server actually sliced rather
        # than returning the same prefix both times.
        page1_ids = {json.dumps(r, sort_keys=True) for r in page1["rows"]}
        page2_ids = {json.dumps(r, sort_keys=True) for r in page2["rows"]}
        assert not (page1_ids & page2_ids)
    finally:
        srv.shutdown()


def test_out_of_range_offset_clamps_to_last_page():
    """Offset past the end should land on the final page, not return
    an empty rows + huge offset. Mirrors the client-side clamp the
    old pager did."""
    tmp = tempfile.mkdtemp()
    _seed_voice_session(tmp, count=75)
    srv, port = _start_server(tmp)
    try:
        out = _get_cat(port, "voice", offset=99999, limit=50)
        assert out["total"] <= 75
        assert out["offset"] < out["total"]
        assert len(out["rows"]) > 0
    finally:
        srv.shutdown()


def test_filters_available_lists_distinct_types_and_channels():
    tmp = tempfile.mkdtemp()
    _seed_voice_session(tmp, count=20)
    srv, port = _start_server(tmp)
    try:
        out = _get_cat(port, "voice", offset=0, limit=5)
        fa = out.get("filters_available", {})
        # 2 channels in the seed (CH1 + CH2), 1 type (PMR446).
        assert "PMR446" in fa.get("types", [])
        assert set(fa.get("channels", [])) >= {"CH1", "CH2"}
    finally:
        srv.shutdown()


def test_type_filter_narrows_result_but_not_filters_available():
    """When the user picks a type, the PAGE narrows but
    `filters_available` still shows every type in the raw set so the
    dropdown doesn't shrink to a single option."""
    tmp = tempfile.mkdtemp()
    _seed_voice_session(tmp, count=20)
    srv, port = _start_server(tmp)
    try:
        unfiltered = _get_cat(port, "voice", offset=0, limit=50)
        filtered = _get_cat(port, "voice", offset=0, limit=50, type="PMR446")
        # Filtered result is a subset (all rows match).
        for r in filtered["rows"]:
            assert r.get("signal_type") == "PMR446"
        # filters_available is identical pre/post filter.
        assert (filtered["filters_available"]["types"]
                == unfiltered["filters_available"]["types"])
    finally:
        srv.shutdown()


def test_channel_filter_narrows_to_single_channel():
    tmp = tempfile.mkdtemp()
    _seed_voice_session(tmp, count=30)
    srv, port = _start_server(tmp)
    try:
        out = _get_cat(port, "voice", offset=0, limit=50, channel="CH1")
        assert out["rows"], "expected at least one CH1 row"
        assert all(r.get("channel") == "CH1" for r in out["rows"])
    finally:
        srv.shutdown()


def test_audio_and_transcript_flags_filter_voice_rows():
    tmp = tempfile.mkdtemp()
    _seed_voice_session(tmp, count=30)
    srv, port = _start_server(tmp)
    try:
        audio_only = _get_cat(port, "voice", offset=0, limit=50, audio="1")
        assert audio_only["rows"], "seed guarantees >= 1 audio row"
        assert all(r.get("audio_file") for r in audio_only["rows"])
        transcript_only = _get_cat(port, "voice", offset=0, limit=50,
                                   transcript="1")
        if transcript_only["rows"]:
            assert all(r.get("transcript") for r in transcript_only["rows"])
        # Audio-only must be a superset of transcript-only (transcripts
        # are attached to audio rows).
        assert audio_only["total"] >= transcript_only["total"]
    finally:
        srv.shutdown()


def test_default_params_are_backward_compatible_shape():
    """Clients that don't send offset/limit still get a well-formed
    response. Ensures the refactor doesn't break anything that skipped
    the pagination flags."""
    tmp = tempfile.mkdtemp()
    _seed_voice_session(tmp, count=10)
    srv, port = _start_server(tmp)
    try:
        out = _get_cat(port, "voice")
        # Keys unchanged from the old response.
        for k in ("category", "label", "rows", "total"):
            assert k in out
        # And new keys are present.
        for k in ("offset", "limit", "filters_available"):
            assert k in out
    finally:
        srv.shutdown()


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
