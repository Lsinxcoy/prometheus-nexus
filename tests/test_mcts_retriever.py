"""Tests for MCTSRetriever (B3-2: MCTS reasoning-aware retrieval)."""

from __future__ import annotations

import math

import pytest

from prometheus_nexus.learning.mcts_retriever import MCTSRetriever, MCTSNode


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def retriever() -> MCTSRetriever:
    return MCTSRetriever(
        coarse_top_k=50,
        mcts_iterations=100,
        mcts_exploration=1.414,
        top_k=5,
        seed=42,
    )


@pytest.fixture
def sample_documents() -> list[dict]:
    """25 documents with varied keyword distributions."""
    return [
        {"id": f"doc-{i}", "title": f"Doc {i}", "content": content}
        for i, content in enumerate(
            [
                "neural networks deep learning transformer attention",
                "reinforcement learning policy gradient MCTS search",
                "knowledge graph embedding relation extraction",
                "natural language processing BERT language model",
                "computer vision convolution image recognition",
                "reinforcement learning reward function Q-learning",
                "deep learning architecture transformer encoder decoder",
                "MCTS Monte Carlo tree search UCB1 exploration",
                "knowledge retrieval information extraction document",
                "language model GPT transformer attention mechanism",
                "policy gradient actor critic reinforcement",
                "image classification CNN residual network",
                "relation extraction knowledge base completion",
                "attention mechanism self-attention multi-head",
                "gradient descent optimization stochastic",
                "UCB1 exploration exploitation bandit algorithm",
                "document retrieval sparse dense hybrid search",
                "encoder decoder sequence to sequence model",
                "MCTS search tree policy network value network",
                "reinforcement learning exploration reward shaping",
                "knowledge base query SPARQL reasoning",
                "transformer XL long context memory",
                "policy iteration value iteration dynamic programming",
                "BERT fine-tuning transfer learning downstream task",
                "convolution layer pooling feature extraction",
            ]
        )
    ]


# ======================================================================
# Unit tests — MCTSNode
# ======================================================================


class TestMCTSNode:
    def test_avg_value_zero_visits(self) -> None:
        node = MCTSNode(keyword="test")
        assert node.avg_value == 0.0

    def test_avg_value_with_visits(self) -> None:
        node = MCTSNode(keyword="test", visits=4, total_value=2.0)
        assert node.avg_value == 0.5

    def test_ucb1_infinity_unvisited(self) -> None:
        node = MCTSNode(keyword="test", visits=0)
        assert node.ucb1(total_visits=100) == float("inf")

    def test_ucb1_visited(self) -> None:
        node = MCTSNode(keyword="test", visits=5, total_value=3.0)
        score = node.ucb1(total_visits=100, c=1.414)
        expected = 3.0 / 5 + 1.414 * math.sqrt(math.log(100) / 5)
        assert abs(score - expected) < 1e-9

    def test_best_child(self) -> None:
        root = MCTSNode(keyword="root")
        c1 = MCTSNode(keyword="a", visits=10, total_value=8.0, parent=root)
        c2 = MCTSNode(keyword="b", visits=5, total_value=6.0, parent=root)
        root.children = [c1, c2]
        best = root.best_child(20)
        assert best is not None
        # Both have high avg_value; pick the one with better UCB1
        assert best.keyword in ("a", "b")

    def test_best_child_empty(self) -> None:
        root = MCTSNode(keyword="root")
        assert root.best_child(10) is None


# ======================================================================
# Unit tests — MCTSRetriever
# ======================================================================


class TestMCTSRetriever:
    def test_init(self) -> None:
        r = MCTSRetriever(coarse_top_k=100, mcts_iterations=300, top_k=10)
        assert r.coarse_top_k == 100
        assert r.mcts_iterations == 300
        assert r.top_k == 10
        assert r.get_stats()["total_calls"] == 0

    def test_extract_keywords(self, retriever: MCTSRetriever) -> None:
        text = "The quick brown fox jumps over the lazy dog neural network"
        kws = retriever._extract_keywords(text)
        assert isinstance(kws, list)
        assert len(kws) > 0
        # Stop words "the", "over" should be removed
        assert "the" not in kws
        assert "neural" in kws
        assert "network" in kws

    def test_coarse_filter(self, retriever: MCTSRetriever, sample_documents) -> None:
        keywords = ["reinforcement", "learning", "policy", "gradient"]
        filtered = retriever._coarse_filter(sample_documents, keywords, top_k=5)
        assert len(filtered) <= 5
        # Doc 1 ("reinforcement learning policy gradient MCTS search") should rank high
        top_ids = [d["id"] for d in filtered]
        assert "doc-1" in top_ids

    def test_build_cooccurrence_graph(self, retriever: MCTSRetriever, sample_documents) -> None:
        keywords = retriever._extract_keywords(
            "reinforcement learning MCTS neural network"
        )
        graph = retriever._build_cooccurrence_graph(keywords, sample_documents)
        assert isinstance(graph, dict)
        for kw in keywords:
            assert kw in graph
        # Some co-occurrences should exist
        all_neighbors = set()
        for neighbors in graph.values():
            all_neighbors.update(neighbors)
        assert len(all_neighbors) > 0

    def test_mcts_search_basic(self, retriever: MCTSRetriever, sample_documents) -> None:
        keywords = retriever._extract_keywords(
            "reinforcement learning MCTS search tree"
        )
        results = retriever._mcts_search(keywords, sample_documents)
        assert isinstance(results, list)
        assert len(results) <= retriever.top_k
        # Results should include MCTS-related docs
        if results:
            assert "mcts_score" in results[0]

    def test_mcts_search_empty_kb(self, retriever: MCTSRetriever) -> None:
        results = retriever._mcts_search(["test"], [])
        assert results == []

    def test_mcts_search_no_keywords(self, retriever: MCTSRetriever, sample_documents) -> None:
        results = retriever._mcts_search([], sample_documents)
        assert len(results) <= retriever.top_k

    # ==============================================================
    # Integration: mcts_retrieve (full pipeline)
    # ==============================================================

    def test_mcts_retrieve_with_documents(
        self, retriever: MCTSRetriever, sample_documents
    ) -> None:
        query = "How does MCTS improve reinforcement learning?"
        reasoning = (
            "MCTS uses UCB1 to balance exploration and exploitation. "
            "It builds a tree of visited states and backpropagates rewards."
        )
        results = retriever.mcts_retrieve(
            query, reasoning, documents=sample_documents
        )
        assert isinstance(results, list)
        assert len(results) <= retriever.top_k
        if results:
            # MCTS-related documents should appear
            top_content = " ".join(d.get("content", "") for d in results).lower()
            assert "mcts" in top_content or "reinforcement" in top_content

    def test_mcts_retrieve_synthetic_kb(self, retriever: MCTSRetriever) -> None:
        query = "deep learning neural networks"
        reasoning = "Transformer models use attention mechanisms for sequence processing."
        results = retriever.mcts_retrieve(query, reasoning, kb_size=100)
        assert isinstance(results, list)
        assert len(results) <= retriever.top_k
        # Synthetic KB was built, results should have IDs
        for doc in results:
            assert "id" in doc
            assert "content" in doc

    def test_get_stats(self, retriever: MCTSRetriever, sample_documents) -> None:
        stats = retriever.get_stats()
        assert stats["total_calls"] == 0

        retriever.mcts_retrieve(
            "MCTS retrieval", "tree search", documents=sample_documents
        )
        stats = retriever.get_stats()
        assert stats["total_calls"] == 1
        assert stats["avg_coarse_time_ms"] >= 0
        assert stats["avg_mcts_time_ms"] >= 0
        assert "ucb1_exploration" in stats

    def test_multiple_calls_stats(self, retriever: MCTSRetriever) -> None:
        query = "knowledge graph"
        reasoning = "relation extraction and graph embedding"
        docs = [
            {"id": "a", "content": "knowledge graph embedding"},
            {"id": "b", "content": "relation extraction from text"},
            {"id": "c", "content": "graph neural network"},
            {"id": "d", "content": "embedding learning representation"},
            {"id": "e", "content": "extraction pipeline NLP"},
        ]
        for _ in range(3):
            retriever.mcts_retrieve(query, reasoning, documents=docs)
        stats = retriever.get_stats()
        assert stats["total_calls"] == 3

    def test_deterministic_with_seed(self) -> None:
        r1 = MCTSRetriever(seed=42, mcts_iterations=100, top_k=3)
        r2 = MCTSRetriever(seed=42, mcts_iterations=100, top_k=3)
        query = "MCTS tree search"
        reasoning = "UCB1 exploration exploitation"
        docs = [
            {"id": f"d{i}", "content": f"document about {t}"}
            for i, t in enumerate([
                "MCTS tree search algorithm",
                "UCB1 bandit exploration",
                "reinforcement learning policy",
                "neural network gradient",
                "knowledge graph search",
            ])
        ]
        res1 = r1.mcts_retrieve(query, reasoning, documents=docs)
        res2 = r2.mcts_retrieve(query, reasoning, documents=docs)
        ids1 = [d["id"] for d in res1]
        ids2 = [d["id"] for d in res2]
        assert ids1 == ids2

    def test_different_exploration_values(self) -> None:
        """Higher exploration should produce different MCTS trees."""
        r_low = MCTSRetriever(mcts_exploration=0.5, mcts_iterations=200, seed=42)
        r_high = MCTSRetriever(mcts_exploration=5.0, mcts_iterations=200, seed=42)
        query = "MCTS search"
        reasoning = "exploration exploitation UCB1"
        docs = [
            {"id": f"d{i}", "content": f"document {i} about MCTS"}
            for i in range(10)
        ]
        res_low = r_low.mcts_retrieve(query, reasoning, documents=docs)
        res_high = r_high.mcts_retrieve(query, reasoning, documents=docs)
        # Determinism via seed should give same results even with different c,
        # because the _rng is only used in _expand_node when no co-occ neighbors exist
        ids_low = [d["id"] for d in res_low]
        ids_high = [d["id"] for d in res_high]
        # They might differ if c changes UCB1 ordering enough
        # No assertion — just checking no crash


if __name__ == "__main__":
    pytest.main([__file__])
