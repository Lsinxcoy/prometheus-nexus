"""Cycle 40 — TelemetryPipeline rolling-window retains only HALF its capacity.

Weakness: ``TelemetryPipeline._on_event`` trims ``self._history[pipe]`` to
``max_window // 2`` snapshots, while the documented ``max_window`` ("每管道最大
保留条数") and the sibling ``record()`` method trim to the full ``max_window``.
The production path (ALL 7 pipeline ``*_completed`` events flow through
``_on_event``) therefore silently keeps only half the intended telemetry
history — shortening every trend window and under-reporting snapshot counts.
Real loop/window logic bug (dimension: 循环深化), distinct from the prior
event_bus dead-letter ``// 2`` bug (cycle 6).
"""
from __future__ import annotations

from types import SimpleNamespace

from prometheus_nexus.lifecycle.telemetry_pipeline import TelemetryPipeline


def _make_pipeline(max_window: int = 50):
    raw = SimpleNamespace(
        fitness_before=0.5,
        fitness_after=0.6,
        result="",
        duration_ms=1.0,
        metadata={},
    )
    omega = SimpleNamespace(_telemetry={"evolve": raw, "learn": raw})
    tp = TelemetryPipeline(omega)
    tp._max_window = max_window
    return tp


def test_on_event_retains_full_window_not_half():
    """After exceeding max_window events, history keeps the FULL window (50),
    not half (~25). Reproduces the bug pre-fix (len != 50 -> assertion fails)."""
    tp = _make_pipeline(max_window=50)
    for _ in range(60):
        tp._on_event({"data": {"type": "evolve_completed"}})
    assert len(tp._history["evolve"]) == tp._max_window  # 50, not ~25


def test_on_event_window_cap_generalizes_across_pipes():
    """The fix is pipe-agnostic: every subscribed pipe caps at full max_window."""
    tp = _make_pipeline(max_window=50)
    for _ in range(60):
        tp._on_event({"data": {"type": "evolve_completed"}})
        tp._on_event({"data": {"type": "learn_completed"}})
    assert len(tp._history["evolve"]) == tp._max_window
    assert len(tp._history["learn"]) == tp._max_window


def test_query_returns_full_retained_window():
    """query(pipe, window=max_window) must expose the full retained window
    (pre-fix it returned only ~25 due to the half-window trim)."""
    tp = _make_pipeline(max_window=50)
    for _ in range(60):
        tp._on_event({"data": {"type": "evolve_completed"}})
    snaps = tp.query("evolve", window=tp._max_window)
    assert isinstance(snaps, list) and len(snaps) == tp._max_window
