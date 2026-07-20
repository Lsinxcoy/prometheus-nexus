"""Tests for trace_engine.py — Trace engine module.

Target coverage increase from 28% to 70%+.
Tests cover all public methods including edge cases.
"""
import time
from collections import deque

import pytest

from prometheus_nexus.safety.trace_engine import (
    TraceStep,
    TraceEngine,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def engine():
    """Create a default TraceEngine instance."""
    return TraceEngine()


@pytest.fixture
def engine_with_limit():
    """Create engine with custom max_traces limit."""
    return TraceEngine(max_traces=10)


# =============================================================================
# Test Initialization
# =============================================================================

class TestInit:
    """Test TraceEngine initialization."""

    def test_default_initialization(self):
        """Should initialize with default parameters."""
        eng = TraceEngine()
        assert eng._confidence_threshold == 0.5
        assert eng._max_traces == 500
        assert eng._traces == {}
        assert eng._trace_order == []

    def test_custom_initialization(self):
        """Should accept custom parameters."""
        eng = TraceEngine(confidence_threshold=0.3, max_traces=100)
        assert eng._confidence_threshold == 0.3
        assert eng._max_traces == 100


# =============================================================================
# Test Start Trace
# =============================================================================

class TestStartTrace:
    """Test starting new traces."""

    def test_start_trace_basic(self, engine):
        """Should create a new trace with ID."""
        trace_id = engine.start_trace("test_trace")
        assert trace_id is not None
        assert len(trace_id) > 0
        assert trace_id in engine._traces

    def test_start_trace_with_metadata(self, engine):
        """Should accept metadata parameter."""
        trace_id = engine.start_trace("test", metadata={"user": "test"})
        assert trace_id in engine._traces

    def test_start_trace_creates_steps(self, engine):
        """Should create start step."""
        trace_id = engine.start_trace("test")
        steps = engine._traces[trace_id]
        assert len(steps) >= 1
        assert steps[0].action == "__start__"

    def test_start_trace_unique_ids(self, engine):
        """Should generate unique trace IDs."""
        time.sleep(0.01)  # Ensure different timestamps
        id1 = engine.start_trace("test")
        time.sleep(0.01)
        id2 = engine.start_trace("test")
        assert id1 != id2

    def test_start_trace_respects_max_traces(self, engine_with_limit):
        """Should remove oldest trace when max exceeded."""
        for i in range(15):
            engine_with_limit.start_trace(f"trace_{i}")
        assert len(engine_with_limit._traces) <= 10


# =============================================================================
# Test Record Step
# =============================================================================

class TestRecordStep:
    """Test recording steps in traces."""

    def test_record_step_basic(self, engine):
        """Should record a step in trace."""
        trace_id = engine.start_trace("test")
        engine.record_step(trace_id, 1, "search", 0.8, "found results")
        steps = engine._traces[trace_id]
        assert len(steps) == 2  # start + step (end added later)

    def test_record_step_structure(self, engine):
        """Should create properly structured step."""
        trace_id = engine.start_trace("test")
        engine.record_step(trace_id, 1, "search", 0.8, "found results")
        steps = engine._traces[trace_id]
        step = steps[1]  # Skip start step
        assert step.step_id == 1
        assert step.action == "search"
        assert step.confidence == 0.8
        assert step.result == "found results"

    def test_record_multiple_steps(self, engine):
        """Should record multiple steps in order."""
        trace_id = engine.start_trace("test")
        for i in range(5):
            engine.record_step(trace_id, i, f"action_{i}", 0.9, f"result_{i}")
        steps = engine._traces[trace_id]
        assert len(steps) == 6  # start + 5 steps (end added later)

    def test_record_step_low_confidence(self, engine):
        """Should record low confidence steps."""
        trace_id = engine.start_trace("test")
        engine.record_step(trace_id, 1, "search", 0.2, "uncertain result")
        steps = engine._traces[trace_id]
        step = steps[1]
        assert step.confidence == 0.2

    def test_record_step_high_confidence(self, engine):
        """Should record high confidence steps."""
        trace_id = engine.start_trace("test")
        engine.record_step(trace_id, 1, "search", 0.9, "clear result")
        steps = engine._traces[trace_id]
        step = steps[1]
        assert step.confidence == 0.9

    def test_record_step_invalid_trace(self, engine):
        """Should handle invalid trace ID gracefully."""
        try:
            engine.record_step("invalid_trace", 1, "action", 0.5, "result")
        except Exception:
            pass  # Expected behavior


# =============================================================================
# Test Get Trace
# =============================================================================

class TestGetTrace:
    """Test retrieving trace history."""

    def test_get_trace_empty(self, engine):
        """Should return None for non-existent trace."""
        result = engine.get_trace("nonexistent")
        assert result is None

    def test_get_trace_exists(self, engine):
        """Should return trace data for existing trace."""
        trace_id = engine.start_trace("test")
        engine.record_step(trace_id, 1, "action", 0.5, "result")
        result = engine.get_trace(trace_id)
        assert result is not None
        assert len(result) > 0
        assert isinstance(result[0], dict)

    def test_get_trace_chronological_order(self, engine):
        """Should return steps in chronological order."""
        trace_id = engine.start_trace("test")
        for i in range(5):
            engine.record_step(trace_id, i, f"action_{i}", 0.5, f"result_{i}")
        result = engine.get_trace(trace_id)
        # get_trace returns replay results (excluding __start__)
        assert len(result) == 5
        assert result[0]["step_id"] == 0


# =============================================================================
# Test Summarize
# =============================================================================

class TestSummarize:
    """Test trace summarization."""

    def test_summarize_empty(self, engine):
        """Should handle empty trace."""
        trace_id = engine.start_trace("empty")
        summary = engine.summarize(trace_id)
        # Empty trace (only __start__ step) returns None
        assert summary is None

    def test_summarize_basic(self, engine):
        """Should create summary of trace."""
        trace_id = engine.start_trace("test")
        engine.record_step(trace_id, 1, "search", 0.8, "found")
        engine.record_step(trace_id, 2, "analyze", 0.6, "processed")
        summary = engine.summarize(trace_id)
        assert summary is not None
        assert hasattr(summary, 'total_steps')
        assert hasattr(summary, 'key_steps')

    def test_summarize_invalid_trace(self, engine):
        """Should handle invalid trace ID."""
        result = engine.summarize("nonexistent")
        assert result is None


# =============================================================================
# Test Detect Critical Points
# =============================================================================

class TestDetectCriticalPoints:
    """Test critical point detection."""

    def test_detect_critical_points(self, engine):
        """Should detect low confidence steps."""
        trace_id = engine.start_trace("test")
        engine.record_step(trace_id, 1, "search", 0.9, "good")
        engine.record_step(trace_id, 2, "analyze", 0.2, "uncertain")
        critical = engine.detect_critical_points(trace_id)
        assert len(critical) > 0
        assert any(c.confidence < 0.5 for c in critical)

    def test_detect_no_critical_points(self, engine):
        """Should return empty list when no critical points."""
        trace_id = engine.start_trace("test")
        for i in range(5):
            engine.record_step(trace_id, i, f"action_{i}", 0.9, f"result_{i}")
        critical = engine.detect_critical_points(trace_id)
        assert len(critical) == 0

    def test_detect_invalid_trace(self, engine):
        """Should handle invalid trace ID."""
        result = engine.detect_critical_points("nonexistent")
        assert result == []


# =============================================================================
# Test Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_long_trace(self, engine):
        """Should handle very long trace."""
        trace_id = engine.start_trace("long_test")
        for i in range(1000):
            engine.record_step(trace_id, i, f"action_{i}", 0.5, f"result_{i}")
        steps = engine._traces[trace_id]
        assert len(steps) == 1001  # start + 1000 steps (end added later)

    def test_special_characters_in_action(self, engine):
        """Should handle special characters in action names."""
        trace_id = engine.start_trace("test")
        engine.record_step(trace_id, 1, "tool-with-dashes", 0.5, "result")
        engine.record_step(trace_id, 2, "tool_with_underscores", 0.5, "result")
        steps = engine._traces[trace_id]
        assert len(steps) == 3  # start + 2 steps

    def test_unicode_in_result(self, engine):
        """Should handle Unicode in result strings."""
        trace_id = engine.start_trace("test")
        engine.record_step(trace_id, 1, "action", 0.5, "结果：成功")
        steps = engine._traces[trace_id]
        assert steps[1].result == "结果：成功"

    def test_zero_confidence(self, engine):
        """Should handle zero confidence."""
        trace_id = engine.start_trace("test")
        engine.record_step(trace_id, 1, "action", 0.0, "unknown")
        steps = engine._traces[trace_id]
        assert steps[1].confidence == 0.0

    def test_one_confidence(self, engine):
        """Should handle maximum confidence."""
        trace_id = engine.start_trace("test")
        engine.record_step(trace_id, 1, "action", 1.0, "certain")
        steps = engine._traces[trace_id]
        assert steps[1].confidence == 1.0
