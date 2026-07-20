"""Regression test for the FiveGates adaptive-threshold dead-code weakness (cycle 13).

Root cause (src/prometheus_nexus/safety/five_gates.py):
    _adapt_thresholds() raises/lowers self._current_min_utility from the recent
    pass-rate (documented contract: pass_rate>0.9 -> raise, pass_rate<0.3 ->
    lower). But _get_dynamic_threshold() overrode that adapted value with a
    fixed history-mean (avg_util*0.3) once >=10 samples accumulated. The result:
    the adaptation was a *dead no-op after warm-up* — the gate never
    tightened/loosened as documented, and a run of passes had no effect on which
    nodes were admitted.

    The pre-existing test_adaptive_threshold_adjustment only checked the
    internal variable (_current_min_utility > 0.1), which is mutated by
    _adapt_thresholds() regardless of whether _get_dynamic_threshold() consults
    it — a fake-green test that passed both before and after the bug. These
    tests assert the adaptation is actually *consulted by evaluate()*.
"""
import pytest

from prometheus_nexus.foundation.schema import Node, NodeType
from prometheus_nexus.safety.five_gates import FiveGates


def _mk(utility: float, surprise: float = 0.1, content: str = "x") -> Node:
    return Node(id="n", type=NodeType.FACT, content=content,
                utility=utility, surprise=surprise)


def test_adaptive_threshold_is_consulted_by_gate():
    """After a run of passes raises the threshold, a borderline node is rejected.

    Before the fix this FAILS: _get_dynamic_threshold returns a fixed
    avg_util*0.3 == 0.15 (for utility=0.5), so a node with utility=0.18 always
    passes no matter how many passes preceded it — the gate never tightens.
    """
    g = FiveGates(adaptive=True)
    # Long run of clearly-passing nodes; each raises the adapted threshold.
    for _ in range(40):
        assert g.evaluate(_mk(0.5), {"current_node_count": 0}).passed

    # _adapt_thresholds() must have raised the adapted threshold well above the
    # old fixed history-mean of 0.15.
    assert g._current_min_utility > 0.15

    # A node whose utility sits BETWEEN the old history-mean (0.15) and the
    # adapted threshold (~0.31) must now be REJECTED — proving the adapted
    # threshold is actually consulted by evaluate(), not shadowed.
    borderline = g.evaluate(_mk(0.18), {"current_node_count": 0})
    assert not borderline.passed
    failed = [c.gate_name for c in borderline.details if not c.passed]
    assert "utility" in failed


def test_adaptive_raises_then_loosens():
    """pass_rate>0.9 raises the threshold; a sustained low pass-rate lowers it."""
    g = FiveGates(adaptive=True)
    for _ in range(40):
        g.evaluate(_mk(0.5), {"current_node_count": 0})
    high = g._current_min_utility
    assert high > 0.1  # raised by the run of passes

    # Sustained failures push pass_rate below 0.3 -> threshold should lower.
    for _ in range(40):
        g.evaluate(_mk(0.05), {"current_node_count": 0})
    assert g._current_min_utility < high


def test_non_adaptive_threshold_is_static():
    """Non-adaptive mode (the production default) keeps a fixed threshold."""
    g = FiveGates()  # adaptive=False
    for _ in range(40):
        g.evaluate(_mk(0.5), {"current_node_count": 0})
    # threshold never moves outside adaptive mode
    assert g._current_min_utility == 0.1
    # a utility=0.18 node still passes against the static 0.1 threshold
    assert g.evaluate(_mk(0.18), {"current_node_count": 0}).passed
