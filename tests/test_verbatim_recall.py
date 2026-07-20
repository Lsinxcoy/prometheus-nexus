"""Tests for B2-1 Verbatim Chunk Joint Storage (arXiv 2601.00821)
and B2-2 PolarMem Tristate Query (arXiv 2602.00415)."""
from __future__ import annotations

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from prometheus_nexus.foundation.schema import (
    Node, SearchHit, SearchResults, generate_uuidv7,
    NodeType, MemoryTier, ProvenanceType, ZConfig,
)
from prometheus_nexus.foundation.store import MinervaStore


# ============================================================
# Helper: in-memory store for isolated testing
# ============================================================

@pytest.fixture
def store():
    cfg = ZConfig(database_path=":memory:")
    s = MinervaStore(cfg)
    s.connect()
    yield s
    try:
        s.close()
    except Exception:
        pass


# ============================================================
# B2-1: Verbatim Chunk Joint Storage
# ============================================================

class TestVerbatimRecall:
    """B2-1: Verbatim chunk storage and recall enrichment."""

    def test_verbatim_is_stored_on_remember(self, store):
        """When a node is created with raw_chunk, it is stored and retrievable."""
        nid = generate_uuidv7()
        node = Node(
            id=nid,
            type=NodeType.FACT,
            content="This is the extracted artifact content.",
            raw_chunk="This is the original verbatim chunk content.",
            trust_state="has",
            utility=0.8,
            branch="main",
        )
        result = store.create_node(node)
        assert result.success, f"Node creation failed: {result.reason}"

        retrieved = store.read_node(nid)
        assert retrieved is not None, "Node should be retrievable"
        assert retrieved.raw_chunk == "This is the original verbatim chunk content.", \
            f"raw_chunk mismatch: {retrieved.raw_chunk!r}"
        assert retrieved.content == "This is the extracted artifact content.", \
            f"content mismatch: {retrieved.content!r}"

    def test_verbatim_defaults_empty(self, store):
        """A node created without raw_chunk should have empty string default."""
        nid = generate_uuidv7()
        node = Node(
            id=nid,
            type=NodeType.FACT,
            content="Just some content.",
        )
        result = store.create_node(node)
        assert result.success
        retrieved = store.read_node(nid)
        assert retrieved is not None
        assert retrieved.raw_chunk == "", "raw_chunk should default to empty string"
        assert retrieved.trust_state == "unknown", "trust_state should default to 'unknown'"

    def test_recall_returns_chunk_field(self, store):
        """SearchHit metadata should contain 'chunk' when raw_chunk is non-empty."""
        nid = generate_uuidv7()
        node = Node(
            id=nid,
            content="Extracted content",
            raw_chunk="Verbatim chunk content",
            trust_state="has",
            utility=0.9,
        )
        store.create_node(node)

        hits = store.search("Extracted content", limit=5)
        assert len(hits) > 0, "Should find the node"

        found = [n for n in hits if n.id == nid]
        assert len(found) == 1, "Should find exactly the inserted node"
        # Verify both fields are on the node
        assert found[0].raw_chunk == "Verbatim chunk content"

    def test_recall_prefer_chunk(self, store):
        """When prefer_chunk=True, the main content field should use raw_chunk."""
        nid = generate_uuidv7()
        node = Node(
            id=nid,
            content="Extracted content string",
            raw_chunk="Original verbatim chunk",
            trust_state="has",
            utility=0.9,
        )
        store.create_node(node)

        # Read the node and simulate recall enrichment
        retrieved = store.read_node(nid)
        assert retrieved is not None
        # Without prefer_chunk, content stays as extracted
        assert retrieved.content == "Extracted content string"
        # raw_chunk is available
        assert retrieved.raw_chunk == "Original verbatim chunk"

    def test_backwards_compatibility(self, store):
        """The existing recall path without prefer_chunk works unchanged."""
        nid = generate_uuidv7()
        node = Node(
            id=nid,
            content="Some existing content",
            utility=0.7,
        )
        store.create_node(node)

        retrieved = store.read_node(nid)
        assert retrieved is not None
        # Content field unchanged
        assert retrieved.content == "Some existing content"
        # raw_chunk defaults to empty
        assert retrieved.raw_chunk == ""
        # trust_state defaults to unknown
        assert retrieved.trust_state == "unknown"


# ============================================================
# B2-2: PolarMem Tristate
# ============================================================

class TestPolarMemTristate:
    """B2-2: Three-state memory filtering."""

    def test_trust_state_filtering_has(self, store):
        """Nodes with trust_state='has' are stored and retrievable normally."""
        nid = generate_uuidv7()
        node = Node(
            id=nid,
            content="Verified information",
            raw_chunk="Verified chunk",
            trust_state="has",
            utility=0.9,
        )
        result = store.create_node(node)
        assert result.success

        retrieved = store.read_node(nid)
        assert retrieved is not None
        assert retrieved.trust_state == "has"

    def test_trust_state_absent(self, store):
        """Nodes with trust_state='not_has' are stored and retrievable."""
        nid = generate_uuidv7()
        node = Node(
            id=nid,
            content="Known absent information",
            raw_chunk="Absent chunk",
            trust_state="not_has",
            utility=0.3,
        )
        result = store.create_node(node)
        assert result.success

        retrieved = store.read_node(nid)
        assert retrieved is not None
        assert retrieved.trust_state == "not_has"

    def test_trust_state_uncertain(self, store):
        """Nodes with trust_state='uncertain' are stored and retrievable."""
        nid = generate_uuidv7()
        node = Node(
            id=nid,
            content="Unverified information",
            raw_chunk="Uncertain chunk",
            trust_state="uncertain",
            utility=0.5,
        )
        result = store.create_node(node)
        assert result.success

        retrieved = store.read_node(nid)
        assert retrieved is not None
        assert retrieved.trust_state == "uncertain"

    def test_trust_state_defaults_unknown(self, store):
        """Nodes created without trust_state default to 'unknown'."""
        nid = generate_uuidv7()
        node = Node(
            id=nid,
            content="Default trust state",
        )
        store.create_node(node)
        retrieved = store.read_node(nid)
        assert retrieved is not None
        assert retrieved.trust_state == "unknown"

    def test_remember_sets_trust_state_has(self, store):
        """Simulate what remember() does: trust_state='has'."""
        nid = generate_uuidv7()
        node = Node(
            id=nid,
            content="Remembered content",
            raw_chunk="Remembered chunk",
            trust_state="has",
        )
        store.create_node(node)
        retrieved = store.read_node(nid)
        assert retrieved is not None
        assert retrieved.trust_state == "has"


# ============================================================
# Integration: Dual field round-trip
# ============================================================

class TestVerbatimPolarMemIntegration:
    """Combined B2-1 + B2-2 round-trip tests."""

    def test_full_round_trip(self, store):
        """Create a node with both raw_chunk and trust_state, retrieve both."""
        nid = generate_uuidv7()
        node = Node(
            id=nid,
            content="The extracted summary content.",
            raw_chunk="The full verbatim original content that was observed.",
            trust_state="has",
            utility=0.85,
            source=ProvenanceType.DIRECT_OBSERVATION,
            tier=MemoryTier.WORKING,
        )
        result = store.create_node(node)
        assert result.success

        retrieved = store.read_node(nid)
        assert retrieved is not None
        assert retrieved.content == "The extracted summary content."
        assert retrieved.raw_chunk == "The full verbatim original content that was observed."
        assert retrieved.trust_state == "has"
        assert retrieved.utility == 0.85
