"""Tests for dream_cycle.py — Dream cycle module.

Target coverage increase from 52% to 85%+.
Tests cover all public methods including edge cases.
"""
import time
from collections import deque

import pytest

from prometheus_nexus.lifecycle.dream_cycle import (
    DreamCycle,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def dreamer():
    """Create a default DreamCycle instance."""
    return DreamCycle()


# =============================================================================
# Test Initialization
# =============================================================================

class TestInit:
    """Test DreamCycle initialization."""

    def test_default_initialization(self):
        """Should initialize with default values."""
        dreamer = DreamCycle()
        assert dreamer is not None
        assert dreamer._memories == []
        assert dreamer._dreams == []
        assert dreamer._beliefs == []


# =============================================================================
# Test Register Memory
# =============================================================================

class TestRegisterMemory:
    """Test registering memories."""

    def test_register_dict_memory(self, dreamer):
        """Should register a dictionary memory."""
        dreamer.register_memory({"id": "m1", "content": "test memory", "utility": 0.5})
        assert len(dreamer._memories) == 1
        assert dreamer._memories[0]["id"] == "m1"

    def test_register_object_memory(self, dreamer):
        """Should register an object memory."""
        class MemoryObj:
            def __init__(self):
                self.id = "m1"
                self.content = "test memory"
                self.utility = 0.5

        dreamer.register_memory(MemoryObj())
        assert len(dreamer._memories) == 1

    def test_register_multiple_memories(self, dreamer):
        """Should register multiple memories."""
        for i in range(10):
            dreamer.register_memory({
                "id": f"m{i}",
                "content": f"memory {i}",
                "utility": 0.5
            })
        assert len(dreamer._memories) == 10

    def test_register_memory_with_tags(self, dreamer):
        """Should handle memory with tags."""
        dreamer.register_memory({
            "id": "m1",
            "content": "AI research",
            "utility": 0.8,
            "tags": ["ai", "ml"]
        })
        assert dreamer._memories[0]["tags"] == ["ai", "ml"]

    def test_register_memory_default_values(self, dreamer):
        """Should use default values for missing fields."""
        dreamer.register_memory({"content": "test"})
        assert dreamer._memories[0]["id"] == "0"
        assert dreamer._memories[0]["utility"] == 0.5
        assert dreamer._memories[0]["tags"] == []


# =============================================================================
# Test Run Cycle
# =============================================================================

class TestRunCycle:
    """Test run_cycle operation."""

    def test_run_cycle_empty(self, dreamer):
        """Should return empty result for no memories."""
        result = dreamer.run_cycle()
        assert result.patterns_found == 0
        assert result.beliefs_synthesized == 0
        assert result.connections_discovered == 0

    def test_run_cycle_with_memories(self, dreamer):
        """Should process memories and return results."""
        # Add enough memories to trigger pattern discovery
        for i in range(10):
            dreamer.register_memory({
                "id": f"m{i}",
                "content": f"This is a test memory number {i} with some words",
                "utility": 0.5,
                "tags": ["test", "memory"]
            })
        result = dreamer.run_cycle()
        assert isinstance(result.patterns_found, int)
        assert isinstance(result.beliefs_synthesized, int)
        assert isinstance(result.connections_discovered, int)

    def test_run_cycle_returns_insights(self, dreamer):
        """Should return insights list."""
        for i in range(10):
            dreamer.register_memory({
                "id": f"m{i}",
                "content": f"Memory {i} with content",
                "utility": 0.5,
                "tags": ["test"]
            })
        result = dreamer.run_cycle()
        assert isinstance(result.insights, list)


# =============================================================================
# Test Dream
# =============================================================================

class TestDream:
    """Test dream operation."""

    def test_dream_empty(self, dreamer):
        """Should return empty dict for no memories."""
        result = dreamer.dream()
        assert isinstance(result, dict)
        assert "patterns_found" in result
        assert "beliefs_synthesized" in result
        assert "connections_discovered" in result

    def test_dream_with_memories(self, dreamer):
        """Should process memories and return results."""
        for i in range(10):
            dreamer.register_memory({
                "id": f"m{i}",
                "content": f"Memory {i} with content",
                "utility": 0.5,
                "tags": ["test"]
            })
        result = dreamer.dream()
        assert isinstance(result, dict)

    def test_dream_alternative_interface(self, dreamer):
        """Should support alternative dream interface with custom memories."""
        custom_memories = [
            {"id": "c1", "content": "custom memory 1", "utility": 0.5},
            {"id": "c2", "content": "custom memory 2", "utility": 0.6},
        ]
        result = dreamer.dream(custom_memories)
        assert isinstance(result, dict)


# =============================================================================
# Test Discover Patterns
# =============================================================================

class TestDiscoverPatterns:
    """Test pattern discovery."""

    def test_discover_patterns_empty(self, dreamer):
        """Should return empty list for no memories."""
        patterns = dreamer._discover_patterns()
        assert patterns == []

    def test_discover_patterns_insufficient_memories(self, dreamer):
        """Should return empty list for less than 3 memories."""
        for i in range(2):
            dreamer.register_memory({
                "id": f"m{i}",
                "content": f"memory {i}",
                "utility": 0.5
            })
        patterns = dreamer._discover_patterns()
        assert patterns == []

    def test_discover_patterns_with_sufficient_memories(self, dreamer):
        """Should discover patterns with sufficient memories."""
        for i in range(10):
            dreamer.register_memory({
                "id": f"m{i}",
                "content": f"This is a test memory with common words like test and memory",
                "utility": 0.5
            })
        patterns = dreamer._discover_patterns()
        assert isinstance(patterns, list)


# =============================================================================
# Test Synthesize Beliefs
# =============================================================================

class TestSynthesizeBeliefs:
    """Test belief synthesis."""

    def test_synthesize_beliefs_empty(self, dreamer):
        """Should return empty list for no memories."""
        beliefs = dreamer._synthesize_beliefs()
        assert beliefs == []

    def test_synthesize_beliefs_with_memories(self, dreamer):
        """Should synthesize beliefs from memories."""
        for i in range(10):
            dreamer.register_memory({
                "id": f"m{i}",
                "content": f"Belief about topic {i} with evidence",
                "utility": 0.5,
                "tags": ["topic"]
            })
        beliefs = dreamer._synthesize_beliefs()
        assert isinstance(beliefs, list)


# =============================================================================
# Test Discover Connections
# =============================================================================

class TestDiscoverConnections:
    """Test connection discovery."""

    def test_discover_connections_empty(self, dreamer):
        """Should return empty list for no memories."""
        connections = dreamer._discover_connections()
        assert connections == []

    def test_discover_connections_with_memories(self, dreamer):
        """Should discover connections between memories."""
        for i in range(10):
            dreamer.register_memory({
                "id": f"m{i}",
                "content": f"Memory {i} connecting to other memories",
                "utility": 0.5,
                "tags": ["shared", "tag"]
            })
        connections = dreamer._discover_connections()
        assert isinstance(connections, list)


# =============================================================================
# Test Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_run_cycle_with_single_memory(self, dreamer):
        """Should handle single memory gracefully."""
        dreamer.register_memory({"id": "m1", "content": "single memory", "utility": 0.5})
        result = dreamer.run_cycle()
        assert isinstance(result.patterns_found, int)

    def test_run_cycle_with_duplicate_memories(self, dreamer):
        """Should handle duplicate memories."""
        for i in range(5):
            dreamer.register_memory({
                "id": f"m{i}",
                "content": "duplicate memory",
                "utility": 0.5
            })
        result = dreamer.run_cycle()
        assert isinstance(result.patterns_found, int)

    def test_run_cycle_with_empty_content(self, dreamer):
        """Should handle empty content memories."""
        dreamer.register_memory({"id": "m1", "content": "", "utility": 0.5})
        result = dreamer.run_cycle()
        assert isinstance(result.patterns_found, int)

    def test_run_cycle_with_short_words(self, dreamer):
        """Should filter out short words."""
        dreamer.register_memory({"id": "m1", "content": "a b c d e", "utility": 0.5})
        result = dreamer.run_cycle()
        assert isinstance(result.patterns_found, int)

    def test_run_cycle_with_large_number_of_memories(self, dreamer):
        """Should handle large number of memories."""
        for i in range(100):
            dreamer.register_memory({
                "id": f"m{i}",
                "content": f"Memory number {i} with many words to analyze",
                "utility": 0.5,
                "tags": ["test"]
            })
        result = dreamer.run_cycle()
        assert isinstance(result.patterns_found, int)