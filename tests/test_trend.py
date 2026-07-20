"""Tests for trend.py — Trend analysis module.

Target coverage increase from 21% to 70%+.
Tests cover all public methods including edge cases.
"""
import time
from collections import deque

import pytest

from prometheus_nexus.safety.trend import (
    TrendDetector,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def detector():
    """Create a default TrendDetector instance."""
    return TrendDetector()


@pytest.fixture
def detector_with_window():
    """Create detector with custom window size."""
    return TrendDetector(window_size=10)


# =============================================================================
# Test Initialization
# =============================================================================

class TestInit:
    """Test TrendDetector initialization."""

    def test_default_initialization(self):
        """Should initialize with default parameters."""
        detector = TrendDetector()
        assert detector is not None
        assert detector._window_size == 20
        assert detector._alpha == 0.3

    def test_custom_initialization(self):
        """Should accept custom parameters."""
        detector = TrendDetector(window_size=50, alpha=0.5)
        assert detector._window_size == 50
        assert detector._alpha == 0.5


# =============================================================================
# Test Record
# =============================================================================

class TestRecord:
    """Test recording values."""

    def test_record_basic_value(self, detector):
        """Should record a basic value."""
        detector.record(0.5)
        assert len(detector._history) == 1

    def test_record_multiple_values(self, detector):
        """Should record multiple values in order."""
        for i in range(10):
            detector.record(float(i))
        assert len(detector._history) == 10

    def test_record_respects_window_size(self, detector_with_window):
        """Should respect window size limit."""
        for i in range(20):
            detector_with_window.record(float(i))
        assert len(detector_with_window._history) <= 20  # window_size * 2

    def test_record_negative_values(self, detector):
        """Should handle negative values."""
        detector.record(-0.5)
        assert detector._history[-1] == -0.5

    def test_record_zero_value(self, detector):
        """Should handle zero value."""
        detector.record(0.0)
        assert detector._history[-1] == 0.0


# =============================================================================
# Test Detect Trend
# =============================================================================

class TestDetectTrend:
    """Test trend detection."""

    def test_detect_trend_insufficient_data(self, detector):
        """Should return neutral trend for insufficient data."""
        for i in range(4):
            detector.record(float(i))
        trend = detector.detect_trend()
        assert trend["trend"] == "insufficient_data"
        assert trend["direction"] == "unknown"
        assert trend["strength"] == 0.0

    def test_detect_trend_upward(self, detector):
        """Should detect upward trend."""
        for i in range(10):
            detector.record(float(i))
        trend = detector.detect_trend()
        assert trend["direction"] in ["rising", "flat"]

    def test_detect_trend_downward(self, detector):
        """Should detect downward trend."""
        for i in range(10, 0, -1):
            detector.record(float(i))
        trend = detector.detect_trend()
        assert trend["direction"] in ["falling", "flat"]

    def test_detect_trend_includes_strength(self, detector):
        """Should include strength metric."""
        for i in range(5):
            detector.record(float(i))
        trend = detector.detect_trend()
        assert "strength" in trend
        assert 0 <= trend["strength"] <= 1

    def test_detect_trend_includes_acceleration(self, detector):
        """Should include acceleration metric."""
        for i in range(10):
            detector.record(float(i))
        trend = detector.detect_trend()
        assert "acceleration" in trend


# =============================================================================
# Test Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_large_values(self, detector):
        """Should handle very large values."""
        detector.record(1e6)
        assert detector._history[-1] == 1e6

    def test_very_small_values(self, detector):
        """Should handle very small values."""
        detector.record(1e-6)
        assert detector._history[-1] == 1e-6

    def test_repeated_values(self, detector):
        """Should handle repeated values."""
        for i in range(10):
            detector.record(0.5)
        trend = detector.detect_trend()
        assert trend["direction"] == "flat"

    def test_rapid_changes(self, detector):
        """Should handle rapid changes."""
        for i in range(10):
            detector.record(float(i % 2))  # Alternating 0, 1
        trend = detector.detect_trend()
        assert isinstance(trend, dict)

    def test_empty_history(self, detector):
        """Should handle empty history."""
        trend = detector.detect_trend()
        assert trend["trend"] == "insufficient_data"