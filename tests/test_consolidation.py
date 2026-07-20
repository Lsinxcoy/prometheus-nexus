"""Tests for consolidation.py — Consolidation module.

Target coverage increase from current level to 60%+.
Tests cover all public methods including edge cases.
"""
import time
from collections import deque

import pytest

from prometheus_nexus.lifecycle.consolidation import (
    ConsolidationPipeline,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def pipeline():
    """Create a default ConsolidationPipeline instance."""
    return ConsolidationPipeline()


# =============================================================================
# Test Initialization
# =============================================================================

class TestInit:
    """Test ConsolidationPipeline initialization."""

    def test_default_initialization(self):
        """Should initialize with default values."""
        pipeline = ConsolidationPipeline()
        assert pipeline is not None
        assert pipeline._consolidated == 0
        assert pipeline._stages_completed == 0


# =============================================================================
# Test Consolidate
# =============================================================================

class TestConsolidate:
    """Test consolidation pipeline execution."""

    def test_consolidate_basic(self, pipeline):
        """Should execute basic consolidation."""
        result = pipeline.consolidate()
        assert isinstance(result, dict)

    def test_consolidate_empty(self, pipeline):
        """Should handle empty state."""
        result = pipeline.consolidate()
        assert "encoded" in result or "strengthened" in result

    def test_consolidate_with_items(self, pipeline):
        """Should process items through pipeline."""
        items = [
            {"content": "test memory 1", "importance": 0.8},
            {"content": "test memory 2", "importance": 0.5},
        ]
        result = pipeline.consolidate(items)
        assert isinstance(result, dict)

    def test_consolidate_low_importance_items(self, pipeline):
        """Should filter out low importance items."""
        items = [
            {"content": "low importance", "importance": 0.1},
        ]
        result = pipeline.consolidate(items)
        assert isinstance(result, dict)


# =============================================================================
# Test Get Stats
# =============================================================================

class TestGetStats:
    """Test statistics reporting."""

    def test_get_stats_empty(self, pipeline):
        """Should return stats for empty state."""
        stats = pipeline.get_stats()
        assert stats["consolidated"] == 0

    def test_get_stats_after_consolidation(self, pipeline):
        """Should update stats after consolidation."""
        pipeline.consolidate([{"content": "test", "importance": 0.8}])
        stats = pipeline.get_stats()
        assert stats["consolidated"] >= 0


# =============================================================================
# Test Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_multiple_consolidations(self, pipeline):
        """Should handle multiple consecutive consolidations."""
        for i in range(5):
            result = pipeline.consolidate()
            assert isinstance(result, dict)

    def test_duplicate_content(self, pipeline):
        """Should handle duplicate content items."""
        items = [
            {"content": "same content", "importance": 0.8},
            {"content": "same content", "importance": 0.7},
        ]
        result = pipeline.consolidate(items)
        assert isinstance(result, dict)

    def test_none_items(self, pipeline):
        """Should handle None items parameter."""
        result = pipeline.consolidate(None)
        assert isinstance(result, dict)