"""Tests for DualPathwayMemory — Verbatim + Compressed Dual Storage."""

from __future__ import annotations

import time

from prometheus_nexus.memory.dual_storage import DualPathwayMemory


def test_store_and_retrieve_verbatim():
    """Store a verbatim item and retrieve it by exact match."""
    ds = DualPathwayMemory()
    result = ds.store_verbatim("mem1", "The quick brown fox jumps over the lazy dog", 0.5)
    assert result["stored"] is True
    assert result["compressed"] is False  # utility < 0.7

    # Retrieve by substring match
    r = ds.retrieve("fox")
    assert len(r["verbatim"]) == 1
    assert r["verbatim"][0]["node_id"] == "mem1"
    assert "fox" in r["verbatim"][0]["content"]
    assert r["total"] >= 1

    # Retrieve non-matching query
    r = ds.retrieve("nonexistent")
    assert len(r["verbatim"]) == 0
    assert r["total"] >= 0

    print("PASS: test_store_and_retrieve_verbatim")


def test_high_utility_auto_compress():
    """Store high-utility item and verify compressed version is auto-created."""
    ds = DualPathwayMemory(compression_threshold_utility=0.7)
    content = "This is a very important memory about AI alignment and safety research that needs to be compressed for broader retrieval across multiple contexts and pathways."
    ds.store_verbatim("mem2", content, 0.85)

    # Should have compressed entry
    assert len(ds._compressed_store) >= 1

    # Retrieve compressed
    r = ds.retrieve("AI alignment", mode="compressed")
    assert len(r["compressed"]) >= 1
    assert "AI alignment" in r["compressed"][0]["content"] or "important" in r["compressed"][0]["content"]

    # Verify compression: summary should start with first 200 chars
    compressed_entry = list(ds._compressed_store.values())[0]
    assert compressed_entry["content"].startswith(content[:50])
    assert compressed_entry["tokens"] > 0
    assert "mem2" in compressed_entry["original_ids"]

    print("PASS: test_high_utility_auto_compress")


def test_auto_mode_short_query():
    """Auto-mode with short query should prefer compressed primary."""
    ds = DualPathwayMemory()
    ds.store_verbatim("m1", "AlphaGo defeated Lee Sedol in 2016", 0.8)
    ds.store_verbatim("m2", "AlphaGo used deep neural networks", 0.9)
    ds.store_verbatim("m3", "AlphaGo Zero was even stronger", 0.85)
    ds.store_verbatim("m4", "Chess engines use similar techniques", 0.6)

    # Short query (≤20 chars) — should prefer compressed
    r = ds.retrieve("chess engine", mode="auto")
    assert len(r["verbatim"]) >= 0
    assert r["primary_mode"] == "compressed"

    print("PASS: test_auto_mode_short_query")


def test_auto_mode_long_query():
    """Auto-mode with long query and sufficient verbatim matches should prefer verbatim."""
    ds = DualPathwayMemory()
    ds.store_verbatim("m1", "Machine learning models for natural language processing tasks", 0.8)
    ds.store_verbatim("m2", "Natural language processing requires large datasets for training", 0.9)
    ds.store_verbatim("m3", "Machine learning natural language processing uses transformer architectures", 0.85)

    # Long query (> 20 chars) with ≥3 verbatim matches — should prefer verbatim
    r = ds.retrieve("natural language processing machine learning models transformers", mode="auto")
    assert r["primary_mode"] == "verbatim"
    assert len(r["verbatim"]) >= 2

    print("PASS: test_auto_mode_long_query")


def test_link_and_unlink():
    """Manually link between verbatim and compressed, then verify bidirectional access."""
    ds = DualPathwayMemory()

    # Store a verbatim item (low utility, won't auto-compress)
    ds.store_verbatim("v1", "Einstein's theory of relativity changed physics forever", 0.5)

    # Manually create a compressed entry (simulating external creation)
    import time as _time
    ds._compressed_store["c1"] = {
        "content": "Relativity theory by Einstein",
        "tokens": 5,
        "original_ids": [],
        "ts": _time.time(),
    }

    # Link
    ds.link_verbatim_to_compressed("v1", "c1")
    assert "c1" in ds._links.get("v1", [])
    assert "v1" in ds._reverse_links.get("c1", [])

    # Bidirectional retrieval
    compressed = ds.get_compressed_for("v1")
    assert len(compressed) == 1
    assert compressed[0]["compressed_id"] == "c1"

    sources = ds.get_verbatim_sources("c1")
    assert len(sources) == 1
    assert sources[0]["node_id"] == "v1"

    print("PASS: test_link_and_unlink")


def test_eviction():
    """Fill memory past budget and verify oldest low-utility entries are evicted."""
    ds = DualPathwayMemory(verbatim_token_budget=200)

    # Store 5 items — each ~50 chars ≈ 12 tokens → ~60 total tokens, under budget
    # Use larger content to trigger eviction
    content = "A" * 100  # ~25 tokens each
    for i in range(10):
        ds.store_verbatim(
            f"m{i}",
            f"{content} Item number {i}",
            0.1 + (i * 0.02),  # increasing utility
        )

    # Budget is 200 tokens; 10 items * ~28 tokens = ~280 → should trigger eviction
    stats = ds.get_stats()
    assert stats["verbatim_count"] < 10, "Eviction should have reduced count"
    assert stats["total_tokens"] <= 200, "Total tokens should be within budget"

    # The evicted entries should be the lowest utility ones
    # m0 should likely be gone (lowest utility)
    remaining_ids = set(ds._verbatim_store.keys())
    assert "m0" not in remaining_ids or any(
        ds._verbatim_store[k]["utility"] > 0.2 for k in ["m0"]
    ), "Lowest utility items should be evicted first"

    # Verify eviction updated token count correctly
    actual_tokens = sum(
        e.get("token_estimate", 0) for e in ds._verbatim_store.values()
    )
    assert actual_tokens <= 200

    print("PASS: test_eviction")


def test_get_stats():
    """Verify stats method returns expected structure."""
    ds = DualPathwayMemory(verbatim_token_budget=1000)
    ds.store_verbatim("s1", "Statistical mechanics", 0.9)
    ds.store_verbatim("s2", "Quantum field theory", 0.6)

    stats = ds.get_stats()
    assert stats["verbatim_count"] == 2
    assert stats["compressed_count"] >= 1  # s1 triggered compress
    assert stats["total_tokens"] > 0
    assert stats["links_count"] >= 1
    assert stats["token_budget_used_pct"] > 0
    assert "avg_compression_ratio" in stats

    print("PASS: test_get_stats")


def test_evict_verbatim_updates_links():
    """Evicting a verbatim should properly update reverse links."""
    ds = DualPathwayMemory()
    ds.store_verbatim("ev1", "Content for eviction test that is important enough to compress", 0.85)

    # Get compressed id
    compressed_ids = list(ds._compressed_store.keys())
    assert len(compressed_ids) == 1
    cid = compressed_ids[0]

    # Evict verbatim
    ds.evict_verbatim("ev1")

    # Verbatim store should not have it
    assert "ev1" not in ds._verbatim_store

    # Compressed entry should still exist (orphaned)
    assert cid in ds._compressed_store
    assert cid in ds._orphaned_compressed

    # Reverse link should be empty
    assert ds._reverse_links.get(cid, []) == []

    print("PASS: test_evict_verbatim_updates_links")


if __name__ == "__main__":
    test_store_and_retrieve_verbatim()
    test_high_utility_auto_compress()
    test_auto_mode_short_query()
    test_auto_mode_long_query()
    test_link_and_unlink()
    test_eviction()
    test_get_stats()
    test_evict_verbatim_updates_links()
    print("\nAll tests passed!")
