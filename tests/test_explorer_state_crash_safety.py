"""Crash-safety tests for ExplorerState persistence.

These tests fail against the OLD implementation (non-atomic `open('w')` write,
silent reset on corruption, no .bak fallback) and pass against the fixed one
(atomic tmp+fsync+os.replace write, .bak of previous good state, corruption
recovery). Reverse-verify: `git stash` the source fix and these tests fail.
"""
import os
import json
import pytest

from prometheus_nexus.learning.explorer_state import ExplorerState


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "explorer_state.json")


def _record_two(es):
    es.record_round("t1", "dom_a", 0.5)
    es.record_round("t2", "dom_b", 0.5)


def test_backup_created_on_flush(path):
    """Fixed _flush backs up the previous good state before overwriting."""
    es = ExplorerState(path)
    _record_two(es)  # 2nd flush copies main -> .bak
    assert os.path.exists(path + ".bak"), "fixed code must create a .bak backup"
    bak = json.load(open(path + ".bak"))
    assert bak["total"] == 1  # backup reflects the prior flush


def test_corruption_recovers_from_backup(path):
    """Main file corrupt -> state is recovered from .bak, NOT silently reset to 0."""
    es = ExplorerState(path)
    _record_two(es)  # main=total2, bak=total1
    # Corrupt the primary file (simulates crash mid-write / disk bit-rot).
    with open(path, "w") as f:
        f.write("{ this is not valid json")
    recovered = ExplorerState(path)  # triggers _load
    assert recovered._total_rounds == 1, "corruption must recover prior good state, not reset to 0"
    assert recovered.get_focus_domain() in ("dom_a", "dom_b")


def test_atomic_write_leaves_no_tmp_residue(path):
    """Atomic write must never leave a stray .tmp file behind."""
    es = ExplorerState(path)
    es.record_round("t", "dom", 0.5)
    assert not os.path.exists(path + ".tmp"), "no .tmp residue after flush"


def test_round_trip_preserves_counts(path):
    """Counts survive a reload from disk."""
    es = ExplorerState(path)
    _record_two(es)
    reloaded = ExplorerState(path)
    assert reloaded._total_rounds == 2
    assert reloaded.get_stats()["domains"] == 2


def test_first_run_no_backup_and_loads_empty(path):
    """Fresh state has no .bak and loads empty without error."""
    es = ExplorerState(path)
    assert es._total_rounds == 0
    assert not os.path.exists(path + ".bak")
