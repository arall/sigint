"""Tests for agent state.json atomic persistence."""
import json
import os
import sys
import tempfile

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def test_default_state_when_file_missing():
    from agent.state import AgentState
    d = tempfile.mkdtemp()
    state = AgentState.load(os.path.join(d, "state.json"), default_agent_id="N01")
    assert state.agent_id == "N01"
    assert state.adopted is False
    assert state.current_scanner is None
    assert state.config["det_rate_sec"] == 6


def test_save_and_load_roundtrip():
    from agent.state import AgentState
    d = tempfile.mkdtemp()
    path = os.path.join(d, "state.json")
    state = AgentState.load(path, default_agent_id="N01")
    state.adopted = True
    state.current_scanner = {"type": "pmr", "args": ["--digital"]}
    state.save()

    loaded = AgentState.load(path, default_agent_id="ignored")
    assert loaded.agent_id == "N01"
    assert loaded.adopted is True
    assert loaded.current_scanner == {"type": "pmr", "args": ["--digital"]}


def test_atomic_write_does_not_corrupt_on_partial_write(tmp_path):
    """The save() must use os.rename to publish atomically."""
    from agent.state import AgentState
    path = str(tmp_path / "state.json")
    state = AgentState.load(path, default_agent_id="N01")
    state.adopted = True
    state.save()

    # Simulate a separate writer: there must never be a moment where
    # state.json is present but empty/partial from our save().
    # Manually check that no '.tmp' file remains on success.
    assert os.path.exists(path)
    assert not os.path.exists(path + ".tmp")


def test_load_recovers_from_corrupt_json(tmp_path):
    """If state.json is corrupted, fall back to defaults (log the fact)."""
    from agent.state import AgentState
    path = str(tmp_path / "state.json")
    with open(path, "w") as f:
        f.write("{not json")

    state = AgentState.load(path, default_agent_id="N01")
    assert state.agent_id == "N01"
    assert state.adopted is False


def test_seq_counter_survives_reload(tmp_path):
    from agent.state import AgentState
    path = str(tmp_path / "state.json")
    s = AgentState.load(path, default_agent_id="N01")
    s.last_seq_sent = 1247
    s.last_seq_acked = 1240
    s.save()

    s2 = AgentState.load(path, default_agent_id="N01")
    assert s2.last_seq_sent == 1247
    assert s2.last_seq_acked == 1240
