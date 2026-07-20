"""Tests for signal_fusion.py — Signal fusion and processing.

Tests cover:
- SignalFusionLayer class initialization
- Basic functionality
"""
from __future__ import annotations
import time
import pytest

from prometheus_nexus.lifecycle.signal_fusion import SignalFusionLayer


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_omega():
    """Create a mock omega object."""
    class MockOmega:
        def __init__(self):
            self.telemetry = {}
            self.bus = None
    return MockOmega()


@pytest.fixture
def sf(mock_omega):
    """Create a default SignalFusionLayer instance."""
    return SignalFusionLayer(mock_omega)


# ============================================================================
# Test Initialization
# ============================================================================

class TestInit:
    """Test SignalFusionLayer initialization."""

    def test_default_initialization(self, mock_omega):
        """Should initialize with omega parameter."""
        sf = SignalFusionLayer(mock_omega)
        assert sf is not None
        assert sf._omega == mock_omega

    def test_chain_stack_initialized(self, sf):
        """Should initialize empty chain stack."""
        assert sf._chain_stack == []

    def test_chains_initialized(self, sf):
        """Should initialize empty chains dict."""
        assert sf._chains == {}

    def test_pipe_results_initialized(self, sf):
        """Should initialize empty pipe results."""
        assert sf._pipe_results == {}

    def test_feedback_queue_initialized(self, sf):
        """Should initialize empty feedback queue."""
        assert sf._feedback_queue == []

    def test_merge_hints_initialized(self, sf):
        """Should initialize empty merge hints."""
        assert sf._merge_hints == {}


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_none_omega(self):
        """Should handle None omega."""
        sf = SignalFusionLayer(None)
        assert sf._omega is None

    def test_empty_chain_stack(self, sf):
        """Should handle empty chain stack operations."""
        assert len(sf._chain_stack) == 0

    def test_empty_feedback_queue(self, sf):
        """Should handle empty feedback queue."""
        assert len(sf._feedback_queue) == 0
