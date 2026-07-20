"""Tests for HeLaMem — Hebbian Learning and Associative Memory (B3-3)."""

import pytest

from prometheus_nexus.memory.hela_mem import HeLaMem


class TestHeLaMem:
    """Unit tests for HeLaMem graph operations."""

    # ---------------------------------------------------------------
    # Initial state
    # ---------------------------------------------------------------

    def test_initial_state(self):
        mem = HeLaMem()
        stats = mem.get_stats()
        assert stats["total_edges"] == 0
        assert stats["unique_nodes"] == 0
        assert stats["avg_weight"] == 0.0
        assert stats["top_hubs"] == []

    def test_default_eta(self):
        mem = HeLaMem()
        assert mem._eta == 0.1

    def test_custom_eta(self):
        mem = HeLaMem(eta=0.5)
        assert mem._eta == 0.5

    # ---------------------------------------------------------------
    # observe_access
    # ---------------------------------------------------------------

    def test_observe_access_creates_edge(self):
        mem = HeLaMem()
        mem.observe_access("node_a", "node_b")
        assert mem.get_edge_weight("node_a", "node_b") == pytest.approx(0.1, rel=1e-6)
        assert mem.get_edge_weight("node_b", "node_a") == pytest.approx(0.1, rel=1e-6)

    def test_observe_access_strengthens_edge(self):
        mem = HeLaMem(eta=0.2)
        mem.observe_access("a", "b")
        mem.observe_access("a", "b")
        assert mem.get_edge_weight("a", "b") == pytest.approx(0.4, rel=1e-6)

    def test_observe_access_caps_at_one(self):
        mem = HeLaMem(eta=0.6)
        mem.observe_access("a", "b")
        mem.observe_access("a", "b")
        assert mem.get_edge_weight("a", "b") == 1.0  # 0.6+0.6 capped

    def test_self_loop_ignored(self):
        mem = HeLaMem(eta=0.5)
        mem.observe_access("a", "a")
        assert mem.get_edge_weight("a", "a") == 0.0
        assert mem.get_stats()["total_edges"] == 0

    def test_multiple_nodes_form_star(self):
        mem = HeLaMem(eta=0.3)
        mem.observe_access("hub", "leaf_a")
        mem.observe_access("hub", "leaf_b")
        mem.observe_access("hub", "leaf_c")
        assert mem.get_edge_weight("hub", "leaf_a") == pytest.approx(0.3, rel=1e-6)
        assert mem.get_edge_weight("hub", "leaf_b") == pytest.approx(0.3, rel=1e-6)
        assert mem.get_edge_weight("hub", "leaf_c") == pytest.approx(0.3, rel=1e-6)
        assert mem.get_stats()["total_edges"] == 3
        assert mem.get_stats()["unique_nodes"] == 4

        # leaf-leaf edges should be zero (no direct co-occurrence)
        assert mem.get_edge_weight("leaf_a", "leaf_b") == 0.0

    def test_repeated_observation(self):
        mem = HeLaMem(eta=0.1)
        for _ in range(5):
            mem.observe_access("x", "y")
        assert mem.get_edge_weight("x", "y") == pytest.approx(0.5, rel=1e-6)

    # ---------------------------------------------------------------
    # get_hub_nodes
    # ---------------------------------------------------------------

    def test_get_hub_nodes_empty(self):
        mem = HeLaMem()
        assert mem.get_hub_nodes() == []

    def test_get_hub_nodes_single_edge(self):
        mem = HeLaMem(eta=0.4)
        mem.observe_access("a", "b")
        hubs = mem.get_hub_nodes(top_k=2)
        assert len(hubs) == 2
        assert hubs[0][1] == pytest.approx(0.4, rel=1e-6)
        assert hubs[1][1] == pytest.approx(0.4, rel=1e-6)

    def test_get_hub_nodes_ranking(self):
        mem = HeLaMem(eta=0.5)
        mem.observe_access("hub1", "a")
        mem.observe_access("hub1", "b")
        mem.observe_access("hub1", "c")
        mem.observe_access("d", "e")
        hubs = mem.get_hub_nodes(top_k=3)
        # hub1 has score 1.5 (3 × 0.5)
        assert hubs[0][0] == "hub1"
        assert hubs[0][1] == pytest.approx(1.5, rel=1e-6)

    def test_get_hub_nodes_top_k_cutoff(self):
        mem = HeLaMem(eta=0.2)
        for i in range(10):
            for j in range(i + 1, 10):
                mem.observe_access(f"node_{i}", f"node_{j}")
        hubs = mem.get_hub_nodes(top_k=3)
        assert len(hubs) <= 3
        # every node has the same degree, so we just verify count
        assert len(hubs) == 3

    # ---------------------------------------------------------------
    # hela_consolidate
    # ---------------------------------------------------------------

    def test_hela_consolidate_empty(self):
        mem = HeLaMem()
        clusters = mem.hela_consolidate()
        assert clusters == {}

    def test_hela_consolidate_identifies_hub_neighbourhoods(self):
        mem = HeLaMem(eta=0.4)
        mem.observe_access("hub", "a")
        mem.observe_access("hub", "b")
        mem.observe_access("hub", "c")
        mem.observe_access("d", "e")  # isolated pair, no hub

        clusters = mem.hela_consolidate(top_k=1)

        # "hub" should be the sole hub cluster
        assert "hub" in clusters
        neighbours = set(clusters["hub"])
        assert neighbours == {"a", "b", "c"}
        assert len(clusters) == 1

    def test_hela_consolidate_multiple_hubs(self):
        mem = HeLaMem(eta=0.5)
        # Hub A
        mem.observe_access("hub_a", "x")
        mem.observe_access("hub_a", "y")
        # Hub B
        mem.observe_access("hub_b", "p")
        mem.observe_access("hub_b", "q")
        mem.observe_access("hub_b", "r")

        clusters = mem.hela_consolidate(top_k=2)
        assert "hub_a" in clusters or "hub_b" in clusters
        # hub_b has higher degree (3 neighbours vs 2)
        if "hub_b" in clusters:
            assert set(clusters["hub_b"]) == {"p", "q", "r"}

    def test_hela_consolidate_no_duplicate_neighbours(self):
        mem = HeLaMem(eta=0.3)
        mem.observe_access("hub", "leaf")
        mem.observe_access("hub", "leaf")  # same edge observed twice
        clusters = mem.hela_consolidate()
        assert "hub" in clusters
        assert clusters["hub"] == ["leaf"]  # deduplicated

    # ---------------------------------------------------------------
    # get_edges
    # ---------------------------------------------------------------

    def test_get_edges_empty(self):
        mem = HeLaMem()
        assert mem.get_edges("nobody") == []

    def test_get_edges_returns_incident_edges(self):
        mem = HeLaMem(eta=0.2)
        mem.observe_access("n", "a")
        mem.observe_access("n", "b")

        edges = mem.get_edges("n")
        assert len(edges) == 2
        targets = {t for _, t, _ in edges}
        assert targets == {"a", "b"}
        for _, _, w in edges:
            assert w == pytest.approx(0.2, rel=1e-6)

    def test_get_edges_symmetric(self):
        mem = HeLaMem(eta=0.3)
        mem.observe_access("x", "y")

        edges_x = mem.get_edges("x")
        edges_y = mem.get_edges("y")
        assert len(edges_x) == 1
        assert len(edges_y) == 1
        assert edges_x[0][1] == "y"
        assert edges_y[0][1] == "x"
        assert edges_x[0][2] == edges_y[0][2]

    # ---------------------------------------------------------------
    # get_edge_weight
    # ---------------------------------------------------------------

    def test_get_edge_weight_missing(self):
        mem = HeLaMem()
        assert mem.get_edge_weight("missing", "ghost") == 0.0

    def test_get_edge_weight_self_loop_zero(self):
        mem = HeLaMem()
        assert mem.get_edge_weight("self", "self") == 0.0

    # ---------------------------------------------------------------
    # get_stats
    # ---------------------------------------------------------------

    def test_get_stats_with_edges(self):
        mem = HeLaMem(eta=0.2)
        mem.observe_access("a", "b")
        mem.observe_access("a", "c")
        stats = mem.get_stats()
        assert stats["total_edges"] == 2
        assert stats["unique_nodes"] == 3
        assert stats["avg_weight"] == pytest.approx(0.2, rel=1e-6)
        assert len(stats["top_hubs"]) >= 1
        assert stats["top_hubs"][0]["node_id"] == "a"
        assert stats["top_hubs"][0]["score"] == pytest.approx(0.4, rel=1e-6)

    def test_get_stats_top_hubs_structure(self):
        mem = HeLaMem(eta=0.1)
        mem.observe_access("z", "y")
        stats = mem.get_stats()
        hub_entry = stats["top_hubs"][0]
        assert "node_id" in hub_entry
        assert "score" in hub_entry


class TestHeLaMemIntegration:
    """Integration-style tests exercising multiple HeLaMem features together."""

    def test_loomo_like_scenario(self):
        """Simulate a minimal LoCoMo-like multi-turn scenario.

        Multiple 'episodes' co-occur with a protagonist hub, building up
        Hebbian edges that identify the hub for consolidation.
        """
        mem = HeLaMem(eta=0.15)

        # Simulate co-occurring memories across turns
        co_activations = [
            ("protagonist", "location_park"),
            ("protagonist", "person_alice"),
            ("protagonist", "object_book"),
            ("protagonist", "event_birthday"),
            ("person_alice", "object_book"),   # Alice and book co-occur
            ("person_alice", "event_birthday"),
        ]
        for n1, n2 in co_activations:
            mem.observe_access(n1, n2)

        # Hub detection: protagonist should be top hub (4 incident edges × 0.15)
        hubs = mem.get_hub_nodes(top_k=3)
        assert hubs[0][0] == "protagonist"
        assert hubs[0][1] == pytest.approx(0.6, rel=1e-6)

        # Consolidation: protagonist's neighbours
        clusters = mem.hela_consolidate(top_k=1)
        assert "protagonist" in clusters
        assert len(clusters["protagonist"]) == 4
        assert "object_book" in clusters["protagonist"]

        # Stats sanity
        stats = mem.get_stats()
        assert stats["total_edges"] == len(co_activations)
        assert stats["unique_nodes"] == 5

    def test_thread_safety_observed(self):
        """Smoke-test: concurrent observe_access calls don't error."""
        import threading

        mem = HeLaMem(eta=0.05)

        def worker(i: int):
            for _ in range(20):
                mem.observe_access(f"node_{i}", f"node_{(i+1) % 10}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = mem.get_stats()
        assert stats["total_edges"] > 0
        assert stats["unique_nodes"] > 0
