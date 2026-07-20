"""Cycle-15 weakness test: StatePersistence crash-safety.

Validates that (1) save() is atomic/durable with a previous-state backup,
and (2) load() recovers from a corrupted primary via .bak, and degrades
LOUDLY (ERROR, not silent WARNING) when both are unusable — instead of the
old behaviour where any load error was swallowed into `return {}` and the
engine silently booted with zero persistent memory.
"""
from __future__ import annotations
import json, os, logging
import pytest

from prometheus_nexus.harness.state_persistence import StatePersistence


class FakeAttr:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class FakeOmega:
    def __init__(self):
        self.dopamine = FakeAttr(_history=[0.1, 0.2], _current_threshold=0.5)
        self.coala = FakeAttr(_working_memory=[{"content": "a", "importance": 0.3}])
        self.four_network = FakeAttr(_networks={"a": [1], "b": [2, 3]})
        self.graph_memory = FakeAttr(_episodes=[1, 2], _episode_count=2)
        self.feedback = FakeAttr(_feedbacks={"x": [1], "y": [2]})
        self.evolution_engine = FakeAttr(_history=[1, 2, 3])
        self.dream = FakeAttr(_memories=[1])
        self._thermo = {"energy": 1.0}
        self._trust = {"m": 0.9}
        self.thermodynamic = FakeAttr()
        self.thermodynamic.get_state = lambda: self._thermo
        self.thermodynamic.set_state = lambda s: setattr(self, "_thermo", s)
        self.knowledge_to_mechanism = FakeAttr()
        self.knowledge_to_mechanism.get_trust_state = lambda: self._trust
        self.knowledge_to_mechanism.set_trust_state = lambda s: setattr(self, "_trust", s)


@pytest.fixture
def tmp_state(tmp_path):
    p = str(tmp_path / "omega_state.json")
    return StatePersistence(path=p)


def test_atomic_save_writes_valid_state_and_leaves_no_tmp(tmp_state):
    omega = FakeOmega()
    tmp_state.save(omega)
    assert os.path.exists(tmp_state._path)
    assert not os.path.exists(tmp_state._path + ".tmp")  # no orphaned temp
    with open(tmp_state._path) as f:
        data = json.load(f)
    assert data["dopamine_threshold"] == 0.5
    assert data["dopamine_history"] == [0.1, 0.2]


def test_save_rotates_backup_of_previous_good_state(tmp_state):
    o1 = FakeOmega()
    o1.dopamine._current_threshold = 0.42
    tmp_state.save(o1)
    # First save: no previous primary -> no backup yet.
    assert not os.path.exists(tmp_state._bak_path)

    o2 = FakeOmega()
    o2.dopamine._current_threshold = 0.99
    tmp_state.save(o2)
    # Second save: backup now holds the FIRST (previous) good state.
    assert os.path.exists(tmp_state._bak_path)
    with open(tmp_state._bak_path) as f:
        bak = json.load(f)
    assert bak["dopamine_threshold"] == 0.42
    with open(tmp_state._path) as f:
        pri = json.load(f)
    assert pri["dopamine_threshold"] == 0.99


def test_load_valid_primary_restores_fields(tmp_state):
    state = {
        "dopamine_threshold": 0.77,
        "dopamine_history": [0.3, 0.4],
        "coala_working": [{"content": "x", "importance": 0.9}],
        "graph_episode_count": 5,
        "evolution_count": 3,
        "thermodynamic_state": {"energy": 2.0},
        "trust_levels": {"m": 0.5},
    }
    with open(tmp_state._path, "w") as f:
        json.dump(state, f)
    omega = FakeOmega()
    loaded = tmp_state.load(omega)
    assert loaded["dopamine_threshold"] == 0.77
    assert omega.dopamine._current_threshold == 0.77
    assert omega.dopamine._history == [0.3, 0.4]
    assert omega.graph_memory._episode_count == 5
    assert omega.evolution_engine._history_loaded is True
    assert omega._thermo == {"energy": 2.0}
    assert omega._trust == {"m": 0.5}


def test_load_missing_file_returns_empty_and_is_silent(tmp_state, caplog):
    omega = FakeOmega()
    with caplog.at_level(logging.ERROR, logger="prometheus_nexus.harness.state_persistence"):
        loaded = tmp_state.load(omega)
    assert loaded == {}
    # First run must not be treated as a corruption error.
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_load_corrupt_primary_recovers_from_backup(tmp_state, caplog):
    # Backup holds a good, complete state.
    good = {"dopamine_threshold": 0.61, "dopamine_history": [0.5], "evolution_count": 1}
    with open(tmp_state._bak_path, "w") as f:
        json.dump(good, f)
    # Primary is corrupted (half-written / tampered).
    with open(tmp_state._path, "w") as f:
        f.write("{ this is not valid json ")

    omega = FakeOmega()
    with caplog.at_level(logging.WARNING, logger="prometheus_nexus.harness.state_persistence"):
        loaded = tmp_state.load(omega)

    # Recovered from backup, not silently empty.
    assert loaded["dopamine_threshold"] == 0.61
    assert omega.dopamine._current_threshold == 0.61
    assert omega.dopamine._history == [0.5]
    assert any("recovered" in r.message and "backup" in r.message for r in caplog.records)


def test_load_both_corrupt_logs_error_and_degrades(tmp_state, caplog):
    with open(tmp_state._path, "w") as f:
        f.write("@@@corrupt@@@")
    with open(tmp_state._bak_path, "w") as f:
        f.write("@@@corrupt-bak@@@")

    omega = FakeOmega()
    with caplog.at_level(logging.ERROR, logger="prometheus_nexus.harness.state_persistence"):
        loaded = tmp_state.load(omega)
    assert loaded == {}
    assert any(r.levelno >= logging.ERROR and "primary AND backup" in r.message
               for r in caplog.records)


def test_load_primary_corrupt_no_backup_logs_error(tmp_state, caplog):
    with open(tmp_state._path, "w") as f:
        f.write("truncated")

    omega = FakeOmega()
    with caplog.at_level(logging.ERROR, logger="prometheus_nexus.harness.state_persistence"):
        loaded = tmp_state.load(omega)
    assert loaded == {}
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    # No .bak was ever created.
    assert not os.path.exists(tmp_state._bak_path)
