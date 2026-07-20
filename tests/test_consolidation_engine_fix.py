"""Regression tests for ConsolidationEngine.consolidate() no-op/data-loss bug.

Weakness (cycle 37): consolidate() computed the merged/pruned memory set
(kept -> conflicts) but then discarded it (`self._buffer = []`), so the
"merge similar / prune low-importance" stages had zero effect and buffered
memories were silently lost. promoted_count was never assigned (always 0),
and run() carried unreachable dead code referencing undefined names.

These tests FAIL against the buggy code (AttributeError on result.kept /
buffer emptied to []) and PASS after the fix retains the consolidated set.
"""
import pytest

from prometheus_nexus.memory.consolidation_engine import ConsolidationEngine


def _mem(mid, content, importance):
    return {"id": mid, "content": content, "importance": importance}


class TestConsolidateKeepsResult:
    def test_explicit_path_returns_kept_set(self):
        eng = ConsolidationEngine()
        items = [
            _mem("a", "the cat sat on the mat", 0.9),
            _mem("b", "the cat sat on the mat", 0.7),  # identical -> merged with a
            _mem("c", "the dog ran in the park", 0.5),  # singleton group
        ]
        res = eng.consolidate(items)
        # a,b merge into 1 kept; c is its own kept -> 2 consolidated memories
        assert len(res.kept) == 2
        assert res.merged_count == 1

    def test_no_arg_path_retains_buffered_memories(self):
        eng = ConsolidationEngine()
        eng.add(_mem("a", "alpha beta gamma", 0.8))
        eng.add(_mem("b", "alpha beta gamma", 0.6))
        res = eng.consolidate()  # no args -> processes internal buffer
        # BEFORE FIX: self._buffer was cleared to [] (data loss).
        assert len(eng._buffer) == 1
        assert res.merged_count == 1

    def test_promoted_count_is_populated_not_zero(self):
        eng = ConsolidationEngine()
        items = [
            _mem("a", "shared memory content here", 0.9),
            _mem("b", "shared memory content here", 0.6),
            _mem("c", "totally different memory text", 0.5),
        ]
        res = eng.consolidate(items)
        # BEFORE FIX: promoted_count was never assigned -> 0.
        assert res.promoted_count == len(res.kept)
        assert res.promoted_count == 2

    def test_low_importance_singleton_is_pruned(self):
        eng = ConsolidationEngine(min_importance=0.3)
        items = [_mem("low", "lonely low value memory", 0.1)]
        res = eng.consolidate(items)
        # single low-importance memory is pruned, not kept
        assert len(res.kept) == 0
        assert res.pruned_count == 1

    def test_run_returns_kept_count_and_avoids_dead_code(self):
        eng = ConsolidationEngine()
        items = [
            _mem("a", "duplicate phrase memory", 0.9),
            _mem("b", "duplicate phrase memory", 0.6),
        ]
        result = eng.run(items)
        # BEFORE FIX: run() had unreachable dead code after return and no 'kept' key.
        assert result["status"] == "success"
        assert "kept" in result
        assert result["kept"] == 1

    def test_empty_buffer_no_arg_is_safe(self):
        eng = ConsolidationEngine()
        res = eng.consolidate()  # empty internal buffer
        assert len(res.kept) == 0
        assert eng._buffer == []
