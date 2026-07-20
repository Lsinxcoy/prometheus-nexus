"""Tests for UtilityDecay.apply_decay(days_elapsed) contract.

Background (cycle 23 weakness):
    UtilityDecay.apply_decay declared and documented a configurable decay
    window ``days_elapsed`` but the body silently ignored it — decay was
    computed purely from wall-clock time. A caller passing ``days_elapsed=30``
    (backfill / simulation / deterministic test) got a NO-OP.

These tests pin the FIXED contract:
    * ``days_elapsed=None`` (default) -> real wall-clock decay (production path)
    * ``days_elapsed=N``            -> N days of decay is honored, overriding
                                       wall-clock (so deterministically testable)

The first test is a reverse-verify: on the OLD buggy code the item registered
"just now" has wall-clock elapsed == 0, so apply_decay(days_elapsed=30) would
NOT decay it and the assertion would fail. On the fixed code it decays.
"""
import time
from prometheus_nexus.memory.utility_decay import UtilityDecay


def _mem(ud: UtilityDecay, item_id: str, score: float = 4.0) -> None:
    """Register a memory-layer item (only memory layer decays)."""
    ud.register(item_id, initial_score=score, layer="memory")


def test_param_explicit_honored_overrides_wallclock_reverse_verify():
    """KEY test: explicit days_elapsed must drive decay, not wall-clock.

    Item was referenced NOW (wall-clock elapsed == 0). Old buggy code ignored
    days_elapsed and used wall-clock -> no decay -> assertion fails. Fixed code
    uses the explicit 30-day window -> decay of 1.0 (DECAY_PER_30_DAYS * 30/30).
    """
    ud = UtilityDecay()
    _mem(ud, "m1", score=4.0)
    ud._entries["m1"].last_referenced = time.time()  # referenced just now

    before = ud._entries["m1"].score
    ud.apply_decay(days_elapsed=30)  # would be a no-op under the old bug
    after = ud._entries["m1"].score

    assert after < before, (
        f"days_elapsed param was ignored (wall-clock used): {before} -> {after}"
    )
    assert after == 3.0, f"expected decay of 1.0, got {before} -> {after}"


def test_param_none_uses_realtime():
    """Default (None) keeps production real-time decay behavior."""
    ud = UtilityDecay()
    _mem(ud, "m2", score=4.0)
    # Referenced 31 real days ago -> should decay under real-time path.
    ud._entries["m2"].last_referenced = time.time() - 31 * 86400

    before = ud._entries["m2"].score
    ud.apply_decay()  # None -> wall-clock
    after = ud._entries["m2"].score

    assert after < before, f"real-time decay did not apply: {before} -> {after}"


def test_param_zero_no_decay():
    """days_elapsed=0 means < 30 day threshold -> no decay."""
    ud = UtilityDecay()
    _mem(ud, "m3", score=4.0)
    ud._entries["m3"].last_referenced = time.time()

    ud.apply_decay(days_elapsed=0)
    assert ud._entries["m3"].score == 4.0


def test_production_default_no_spurious_decay():
    """Freshly referenced item under default (None) path must NOT decay."""
    ud = UtilityDecay()
    _mem(ud, "m6", score=4.0)
    ud._entries["m6"].last_referenced = time.time()

    ud.apply_decay()  # real-time: 0 days elapsed -> no decay
    assert ud._entries["m6"].score == 4.0


def test_only_memory_layer_decays():
    """Knowledge-layer items must never decay, even with explicit window."""
    ud = UtilityDecay()
    ud.register("k1", initial_score=4.0, layer="knowledge")
    ud.apply_decay(days_elapsed=30)
    assert ud._entries["k1"].score == 4.0  # knowledge layer is exempt

    # And a memory-layer sibling does decay with the same call.
    _mem(ud, "m4b", score=4.0)
    ud._entries["m4b"].last_referenced = time.time()
    ud.apply_decay(days_elapsed=30)
    assert ud._entries["m4b"].score == 3.0


def test_deletion_candidate_flagged():
    """Long-unreferenced low-score memory item becomes a deletion candidate."""
    ud = UtilityDecay()
    _mem(ud, "m4", score=2.0)  # below DELETION_THRESHOLD (3.0)
    ud.apply_decay(days_elapsed=40)  # elapsed 40 > DELETION_DAYS_UNUSED (30)
    assert ud._entries["m4"].is_candidate_for_deletion is True


def test_stats_decayed_counter():
    """decayed stat increments exactly once per decayed item."""
    ud = UtilityDecay()
    _mem(ud, "m5", score=4.0)
    ud._entries["m5"].last_referenced = time.time()
    ud.apply_decay(days_elapsed=30)
    assert ud.get_stats()["decayed"] == 1


def test_docstring_example_runs():
    """The module's own usage example must not raise."""
    ud = UtilityDecay()
    ud.register("k001", initial_score=4.0, layer="knowledge")
    ud.reference("k001")
    ud.apply_decay(30)  # explicit 30-day window override
    assert ud.get_deletion_candidates() is not None
