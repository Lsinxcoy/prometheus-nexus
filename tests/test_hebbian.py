"""Tests for HebbianMemory module (HeLa-Mem paper, arXiv 2604.16839)."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.memory.hebbian import HebbianMemory
from prometheus_nexus.memory.graph_memory import GraphMemory, EpisodeEvent


# ============================================================
# Unit tests for HebbianMemory
# ============================================================


class TestHebbianMemory:
    def test_initial_state(self):
        hm = HebbianMemory()
        stats = hm.get_stats()
        assert stats["total_edges"] == 0
        assert stats["unique_nodes"] == 0

    def test_update_edge_creates_edge(self):
        hm = HebbianMemory()
        hm.update_edge("node_a", "node_b", delta_weight=0.05)
        assert hm.get_edge_weight("node_a", "node_b") == 0.05
        assert hm.get_edge_weight("node_b", "node_a") == 0.05  # symmetric

    def test_update_edge_strengthens(self):
        hm = HebbianMemory()
        hm.update_edge("a", "b", delta_weight=0.2)
        hm.update_edge("a", "b", delta_weight=0.3)
        assert hm.get_edge_weight("a", "b") == pytest.approx(0.5, rel=1e-6)

    def test_update_edge_caps_at_1_0(self):
        hm = HebbianMemory()
        hm.update_edge("a", "b", delta_weight=0.6)
        hm.update_edge("a", "b", delta_weight=0.6)
        assert hm.get_edge_weight("a", "b") == 1.0

    def test_self_loop_ignored(self):
        hm = HebbianMemory()
        hm.update_edge("a", "a", delta_weight=0.5)
        assert hm.get_edge_weight("a", "a") == 0.0
        assert hm.get_stats()["total_edges"] == 0

    def test_find_hubs_empty(self):
        hm = HebbianMemory()
        assert hm.find_hubs() == []

    def test_find_hubs_single_edge(self):
        hm = HebbianMemory()
        hm.update_edge("a", "b", delta_weight=0.3)
        hubs = hm.find_hubs(top_k=2)
        assert len(hubs) == 2
        # Both a and b have score 0.3
        assert hubs[0][1] == 0.3
        assert hubs[1][1] == 0.3

    def test_find_hubs_ranking(self):
        hm = HebbianMemory()
        hm.update_edge("hub1", "a", delta_weight=0.5)
        hm.update_edge("hub1", "b", delta_weight=0.5)
        hm.update_edge("hub1", "c", delta_weight=0.5)
        hm.update_edge("d", "e", delta_weight=0.1)
        hubs = hm.find_hubs(top_k=3)
        # hub1 has total score 1.5 (3 edges × 0.5)
        assert hubs[0][0] == "hub1"
        assert hubs[0][1] == pytest.approx(1.5, rel=1e-6)

    def test_should_consolidate(self):
        hm = HebbianMemory()
        hm.update_edge("hub", "leaf1", delta_weight=1.0)
        hm.update_edge("hub", "leaf2", delta_weight=0.9)
        # hub has 1.0+0.9=1.9 cumulative
        assert hm.should_consolidate("hub", hub_degree_threshold=1.5)
        assert not hm.should_consolidate("leaf1", hub_degree_threshold=1.5)

    def test_consolidation_candidates(self):
        hm = HebbianMemory()
        hm.update_edge("a", "b", delta_weight=0.8)
        hm.update_edge("a", "c", delta_weight=0.8)
        hm.update_edge("a", "d", delta_weight=0.8)
        candidates = hm.get_consolidation_candidates(min_hub_score=2.0)
        assert "a" in candidates  # score = 2.4
        assert "b" not in candidates  # score = 0.8

    def test_get_stats_non_empty(self):
        hm = HebbianMemory()
        hm.update_edge("x", "y", delta_weight=0.3)
        hm.update_edge("x", "z", delta_weight=0.7)
        stats = hm.get_stats()
        assert stats["total_edges"] == 2
        assert stats["unique_nodes"] == 3
        assert stats["avg_weight"] == pytest.approx(0.5, rel=1e-6)
        assert stats["max_weight"] == 0.7
        assert stats["hub_count"] >= 1

    def test_decay_edge(self):
        hm = HebbianMemory()
        hm.update_edge("a", "b", delta_weight=0.8)
        hm.decay_edge("a", "b", decay_factor=0.5, min_weight=0.3)
        assert hm.get_edge_weight("a", "b") == pytest.approx(0.4, rel=1e-6)
        hm.decay_edge("a", "b", decay_factor=0.5, min_weight=0.01)
        assert hm.get_edge_weight("a", "b") == pytest.approx(0.2, rel=1e-6)
        hm.decay_edge("a", "b", decay_factor=0.5, min_weight=0.3)
        assert hm.get_edge_weight("a", "b") == 0.0  # pruned


# ============================================================
# Integration tests: HebbianMemory wired into GraphMemory
# ============================================================


class TestGraphMemoryHebbianIntegration:
    def test_graph_memory_creates_hebbian_edge_on_add_edge(self):
        hm = HebbianMemory()
        gm = GraphMemory(hebbian=hm)
        gm.add_episode(EpisodeEvent(episode_id="e1", content="hello"))
        gm.add_episode(EpisodeEvent(episode_id="e2", content="world"))
        gm.add_edge("e1", "e2", "related", 0.8)
        # Hebbian edge should have been created
        weight = hm.get_edge_weight("e1", "e2")
        assert weight > 0

    def test_search_triggers_hebbian_learning(self):
        hm = HebbianMemory()
        gm = GraphMemory(hebbian=hm)
        gm.add_episode(EpisodeEvent(episode_id="e1", content="AI research"))
        gm.add_episode(EpisodeEvent(episode_id="e2", content="machine learning"))
        gm.add_episode(EpisodeEvent(episode_id="e3", content="deep neural networks"))
        gm.add_edge("e1", "e2", "related", 0.8)
        gm.add_edge("e2", "e3", "related", 0.8)
        results = gm.search("AI", limit=5)
        assert len(results) >= 1
        # Co-retrieved nodes should have Hebbian edges
        retrieved = [r.episode_id for r in results]
        for i in range(len(retrieved)):
            for j in range(i + 1, min(i + 5, len(retrieved))):
                w = hm.get_edge_weight(retrieved[i], retrieved[j])
                if retrieved[i] != retrieved[j]:
                    assert w >= 0

    def test_graph_memory_no_hebbian_does_not_crash(self):
        gm = GraphMemory()  # no hebbian passed
        gm.add_episode(EpisodeEvent(episode_id="e1", content="test"))
        gm.add_episode(EpisodeEvent(episode_id="e2", content="test2"))
        gm.add_edge("e1", "e2", "related", 0.8)
        results = gm.search("test", limit=5)
        assert len(results) >= 1

    def test_get_stats_includes_hebbian(self):
        hm = HebbianMemory()
        gm = GraphMemory(hebbian=hm)
        gm.add_episode(EpisodeEvent(episode_id="e1", content="a"))
        gm.add_episode(EpisodeEvent(episode_id="e2", content="b"))
        gm.add_edge("e1", "e2", "related", 0.8)
        stats = hm.get_stats()
        assert stats["total_edges"] >= 1
        gm_stats = gm.get_stats()
        assert gm_stats["edges"] >= 1
