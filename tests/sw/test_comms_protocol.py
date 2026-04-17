"""Tests for the Meshtastic C2 wire protocol."""
import sys
import os

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def test_encode_cmd_start():
    from comms.protocol import encode_cmd
    assert encode_cmd("N01", "START", ["pmr", "--digital"]) == "CMD|N01|START|pmr|--digital"


def test_encode_cmd_broadcast_status():
    from comms.protocol import encode_cmd
    assert encode_cmd("*", "STATUS", []) == "CMD|*|STATUS"


def test_encode_det_roundtrip():
    from comms.protocol import encode_det, decode
    wire = encode_det(
        agent_id="N01", seq=1247, type_="pmr", freq_mhz=446.00625,
        rssi=-62, lat=48.1234, lon=2.4567, ts_unix=1744812345, summary="ch3",
    )
    assert wire == "DET|N01|1247|pmr|446.00625|-62|48.1234|2.4567|1744812345|ch3"
    msg = decode(wire)
    assert msg.tag == "DET"
    assert msg.agent_id == "N01"
    assert msg.seq == 1247
    assert msg.fields["type"] == "pmr"
    assert msg.fields["freq_mhz"] == 446.00625
    assert msg.fields["rssi"] == -62
    assert msg.fields["lat"] == 48.1234
    assert msg.fields["lon"] == 2.4567
    assert msg.fields["ts_unix"] == 1744812345
    assert msg.fields["summary"] == "ch3"


def test_encode_stat_roundtrip():
    from comms.protocol import encode_stat, decode
    wire = encode_stat(
        agent_id="N01", seq=15, scanner="pmr", state="running",
        lat=48.123, lon=2.456, sats=9, cpu=42, uptime_sec=3600,
    )
    msg = decode(wire)
    assert msg.tag == "STAT"
    assert msg.fields["scanner"] == "pmr"
    assert msg.fields["state"] == "running"
    assert msg.fields["cpu"] == 42


def test_encode_hello():
    from comms.protocol import encode_hello, decode
    wire = encode_hello("N01", "0.1", "rpi0w")
    assert wire == "HELLO|N01|0.1|rpi0w"
    msg = decode(wire)
    assert msg.tag == "HELLO"
    assert msg.fields["version"] == "0.1"
    assert msg.fields["hw"] == "rpi0w"


def test_encode_ack_and_res():
    from comms.protocol import encode_ack, encode_res, decode
    assert encode_ack("N01", 1247) == "ACK|N01|1247|ok"
    msg = decode("ACK|N01|1247|ok")
    assert msg.tag == "ACK"
    assert msg.fields["seq"] == 1247
    assert msg.fields["status"] == "ok"

    assert encode_res("N01", "START", "ok", "pid 1234") == "RES|N01|START|ok|pid 1234"
    msg = decode("RES|N01|START|ok|pid 1234")
    assert msg.tag == "RES"
    assert msg.fields["verb"] == "START"
    assert msg.fields["result"] == "ok"
    assert msg.fields["msg"] == "pid 1234"


def test_encode_cfg():
    from comms.protocol import encode_cfg
    assert encode_cfg("N01", "det_rate_sec", "4") == "CFG|N01|det_rate_sec|4"


def test_encode_approve():
    from comms.protocol import encode_approve
    assert encode_approve("N01") == "APPROVE|N01"


def test_encode_log():
    from comms.protocol import encode_log, decode
    wire = encode_log("N01", 42, "warn", "rtl_sdr lost")
    msg = decode(wire)
    assert msg.tag == "LOG"
    assert msg.fields["level"] == "warn"
    assert msg.fields["text"] == "rtl_sdr lost"


def test_escape_pipe_in_text_field():
    """Literal '|' in text fields is escaped as %7C."""
    from comms.protocol import encode_log, decode
    wire = encode_log("N01", 1, "info", "a|b|c")
    msg = decode(wire)
    assert msg.fields["text"] == "a|b|c"


def test_decode_unknown_tag_raises():
    from comms.protocol import decode, ProtocolError
    import pytest
    with pytest.raises(ProtocolError):
        decode("ZZZ|N01|foo")


def test_decode_malformed_raises():
    from comms.protocol import decode, ProtocolError
    import pytest
    with pytest.raises(ProtocolError):
        decode("CMD")   # too few fields


def test_truncate_det_for_payload_limit():
    """When the DET wire form exceeds the limit, trailing optional fields are
    dropped in order: summary -> lat/lon -> ts_unix."""
    from comms.protocol import encode_det_truncated
    wire = encode_det_truncated(
        agent_id="N01", seq=1, type_="pmr", freq_mhz=446.00625, rssi=-62,
        lat=48.1234, lon=2.4567, ts_unix=1744812345,
        summary="x" * 300,   # forces truncation
        max_bytes=60,
    )
    assert len(wire.encode("utf-8")) <= 60
    assert wire.startswith("DET|N01|1|pmr|")


def test_protocol_error_on_field_count_mismatch():
    from comms.protocol import decode, ProtocolError
    import pytest
    with pytest.raises(ProtocolError):
        decode("DET|N01|1|pmr|446.00625")  # missing fields
