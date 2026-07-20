"""MCTSRetriever — MCTS reasoning-aware retrieval (arXiv 2601.00003).

Two-phase retrieval:
  Phase 1 (coarse): narrow knowledge base to topic-relevant sub-region
    via keyword intersection from the query and reasoning chain.
  Phase 2 (fine): MCTS traversal over keyword nodes to find
    reasoning-relevant content using UCB1 selection.

Algorithm (per paper):
  mcts_retrieve(query, reasoning_chain, kb_size):
    1. Extract keywords from query + reasoning_chain
    2. Score each KB doc by keyword intersection → coarse subset
    3. Build keyword co-occurrence graph on the coarse subset
    4. MCTS search: UCB1 selection → expand → backpropagate
    5. Return top-N documents
"""

from __future__ import annotations

import logging
import math
import random
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MCTSNode:
    """A node in the MCTS keyword tree.

    Attributes
    ----------
    keyword : str
        The keyword this node represents.
    parent : MCTSNode | None
        Parent node (None for root).
    children : list[MCTSNode]
        Child nodes.
    visits : int
        Number of times this node has been visited.
    total_value : float
        Sum of relevance values from rollouts through this node.
    """
    keyword: str
    parent: MCTSNode | None = None
    children: list[MCTSNode] = field(default_factory=list)
    visits: int = 0
    total_value: float = 0.0

    @property
    def avg_value(self) -> float:
        """Mean value of this node (Q in UCB1)."""
        return self.total_value / max(self.visits, 1)

    def ucb1(self, total_visits: int, c: float = 1.414) -> float:
        """UCB1 score = Q + c * sqrt(ln(N) / n)."""
        if self.visits == 0:
            return float("inf")
        exploitation = self.avg_value
        exploration = c * math.sqrt(math.log(max(total_visits, 1)) / self.visits)
        return exploitation + exploration

    def best_child(self, total_visits: int, c: float = 1.414) -> MCTSNode | None:
        """Select the child with highest UCB1 score."""
        if not self.children:
            return None
        return max(self.children, key=lambda ch: ch.ucb1(total_visits, c))

    def __repr__(self) -> str:
        return (
            f"MCTSNode(keyword={self.keyword!r}, visits={self.visits}, "
            f"avg_value={self.avg_value:.3f})"
        )


# ---------------------------------------------------------------------------
# MCTS Retriever
# ---------------------------------------------------------------------------


class MCTSRetriever:
    """MCTS-driven reasoning-aware retrieval.

    Two-phase pipeline:
    1. **Coarse** — narrow the full KB (``kb_size`` docs) to a topic-relevant
       subset via keyword intersection with the query and reasoning chain.
    2. **Fine** — build a keyword co-occurrence graph on the subset, run MCTS
       with UCB1 selection, and return top documents.

    Parameters
    ----------
    coarse_top_k : int
        Number of documents to keep after coarse filtering (default 200).
    mcts_iterations : int
        MCTS simulation budget (default 500).
    mcts_exploration : float
        UCB1 exploration constant *c* (default sqrt(2) ≈ 1.414).
    top_k : int
        Number of final documents to return (default 20).
    seed : int | None
        Random seed for reproducibility.
    """

    def __init__(
        self,
        coarse_top_k: int = 200,
        mcts_iterations: int = 500,
        mcts_exploration: float = 1.414,
        top_k: int = 20,
        seed: int | None = None,
    ) -> None:
        self.coarse_top_k = coarse_top_k
        self.mcts_iterations = mcts_iterations
        self.mcts_exploration = mcts_exploration
        self.top_k = top_k

        self._rng = random.Random(seed)
        self._stats: dict[str, Any] = {
            "total_calls": 0,
            "avg_coarse_time_ms": 0.0,
            "avg_mcts_time_ms": 0.0,
            "avg_coarse_docs": 0.0,
            "avg_mcts_nodes": 0.0,
            "ucb1_exploration": mcts_exploration,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def mcts_retrieve(
        self,
        query: str,
        reasoning_chain: str,
        kb_size: int = 1000,
        documents: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Full two-phase retrieval pipeline.

        Parameters
        ----------
        query : str
            The original user query.
        reasoning_chain : str
            The reasoning chain / context from the LLM (or a related text).
        kb_size : int
            Total size of the knowledge base to simulate (used if
            ``documents`` is not provided).
        documents : list[dict] | None
            Pre-existing list of documents. Each dict should have at least
            ``"content"`` (str) and optionally ``"id"``, ``"title"``.
            If ``None``, synthetic documents are generated.

        Returns
        -------
        list[dict]
            Top-``top_k`` documents sorted by MCTS relevance score, each
            augmented with an ``"mcts_score"`` key.
        """
        self._stats["total_calls"] += 1
        start = time.time()

        # --- Phase 1: coarse keyword filtering ---
        t0 = time.time()
        keywords = self._extract_keywords(f"{query} {reasoning_chain}")
        if documents is None:
            documents = self._make_synthetic_kb(kb_size, keywords)
        coarse_docs = self._coarse_filter(documents, keywords, self.coarse_top_k)
        coarse_time = (time.time() - t0) * 1000

        # --- Phase 2: MCTS fine retrieval ---
        t1 = time.time()
        results = self._mcts_search(keywords, coarse_docs)
        mcts_time = (time.time() - t1) * 1000

        # --- Update rolling stats ---
        n = self._stats["total_calls"]
        self._stats["avg_coarse_time_ms"] += (coarse_time - self._stats["avg_coarse_time_ms"]) / n
        self._stats["avg_mcts_time_ms"] += (mcts_time - self._stats["avg_mcts_time_ms"]) / n
        self._stats["avg_coarse_docs"] += (len(coarse_docs) - self._stats["avg_coarse_docs"]) / n
        self._stats["avg_mcts_nodes"] += (
            self._stats.get("_last_mcts_nodes", 0) - self._stats["avg_mcts_nodes"]
        ) / n

        logger.debug(
            "mcts_retrieve: query=%r coarse=%d docs in %.1fms, "
            "mcts=%.1fms, returned=%d",
            query[:60],
            len(coarse_docs),
            coarse_time,
            mcts_time,
            len(results),
        )
        return results

    def get_stats(self) -> dict[str, Any]:
        """Return retriever statistics."""
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Phase 1 — Coarse keyword filtering
    # ------------------------------------------------------------------

    def _extract_keywords(self, text: str, max_keywords: int = 30) -> list[str]:
        """Extract meaningful keywords from text."""
        # Lowercase, split on non-alpha
        words = re.findall(r"[a-zA-Z]\w{2,}", text.lower())
        # Filter stop words (short common words)
        stop_words = {
            "the", "and", "for", "are", "but", "not", "you", "all", "can",
            "had", "her", "was", "one", "our", "out", "has", "have", "been",
            "its", "how", "why", "what", "when", "where", "who", "which",
            "this", "that", "with", "from", "they", "them", "their", "will",
            "would", "could", "should", "about", "into", "over", "also",
            "than", "then", "some", "such", "only", "other", "more", "very",
            "just", "make", "like", "know", "well", "back", "still", "much",
            "here", "there", "these", "those", "each", "both", "every",
        }
        filtered = [w for w in words if w not in stop_words and len(w) > 2]
        # Keep most frequent
        counts = Counter(filtered)
        return [w for w, _ in counts.most_common(max_keywords)]

    def _coarse_filter(
        self,
        documents: list[dict[str, Any]],
        keywords: list[str],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Score documents by keyword intersection (coarse phase)."""
        kw_set = set(keywords)
        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in documents:
            content = doc.get("content", doc.get("text", ""))
            doc_keywords = self._extract_keywords(content, max_keywords=50)
            intersection = len(kw_set & set(doc_keywords))
            # Jaccard-like score
            union = len(kw_set | set(doc_keywords))
            score = intersection / max(union, 1)
            scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]

    # ------------------------------------------------------------------
    # Phase 2 — MCTS keyword tree search
    # ------------------------------------------------------------------

    def _mcts_search(
        self,
        keywords: list[str],
        relevant_kb: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """MCTS tree search over keywords.

        Builds a keyword co-occurrence graph from the relevant KB, then
        runs MCTS (UCB1 selection) to find the most reasoning-relevant
        documents.
        """
        if not relevant_kb or not keywords:
            return relevant_kb[: self.top_k]

        # Build keyword co-occurrence graph
        co_graph = self._build_cooccurrence_graph(keywords, relevant_kb)

        # Build MCTS tree
        root_keyword = keywords[0] if keywords else "root"
        root = MCTSNode(keyword=root_keyword)
        self._expand_node(root, co_graph, keywords)

        # Run MCTS simulations
        for _ in range(self.mcts_iterations):
            # 1. SELECT
            selected = self._select(root)
            # 2. EXPAND (if not terminal)
            if selected and len(selected.children) < len(co_graph.get(selected.keyword, [])):
                self._expand_node(selected, co_graph, keywords)
            # 3. SIMULATE
            value = self._simulate(selected, relevant_kb, keywords)
            # 4. BACKPROPAGATE
            self._backpropagate(selected, value)

        # Score documents by MCTS results
        scored = self._score_documents_by_mcts(root, keywords, relevant_kb)
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [doc for _, doc in scored[: self.top_k]]

        # Augment with MCTS score
        for score, doc in scored[: self.top_k]:
            doc["mcts_score"] = round(score, 4)

        self._stats["_last_mcts_nodes"] = self._count_nodes(root)
        return results

    def _build_cooccurrence_graph(
        self,
        keywords: list[str],
        documents: list[dict[str, Any]],
    ) -> dict[str, set[str]]:
        """Build keyword co-occurrence graph from documents."""
        graph: dict[str, set[str]] = {kw: set() for kw in keywords}
        kw_set = set(keywords)

        for doc in documents:
            content = doc.get("content", doc.get("text", ""))
            doc_kws = set(self._extract_keywords(content, max_keywords=50))
            present = kw_set & doc_kws
            for kw1 in present:
                for kw2 in present:
                    if kw1 < kw2:
                        graph[kw1].add(kw2)
                        graph[kw2].add(kw1)
        return graph

    def _expand_node(
        self,
        node: MCTSNode,
        co_graph: dict[str, set[str]],
        all_keywords: list[str],
    ) -> None:
        """Add child nodes from co-occurrence graph."""
        neighbors = co_graph.get(node.keyword, [])
        existing_kws = {ch.keyword for ch in node.children}
        # Add unvisited neighbors as children
        for kw in neighbors:
            if kw not in existing_kws:
                child = MCTSNode(keyword=kw, parent=node)
                node.children.append(child)
                existing_kws.add(kw)
        # If no co-occ neighbors, add random unconnected keywords
        if not node.children:
            candidates = [kw for kw in all_keywords if kw != node.keyword and kw not in existing_kws]
            if candidates:
                chosen = self._rng.choice(candidates)
                child = MCTSNode(keyword=chosen, parent=node)
                node.children.append(child)

    def _select(self, root: MCTSNode) -> MCTSNode:
        """Traverse tree using UCB1 until a leaf or unexpanded node."""
        node = root
        total_visits = root.visits
        while node.children:
            # If any child unvisited, pick it
            unvisited = [ch for ch in node.children if ch.visits == 0]
            if unvisited:
                return self._rng.choice(unvisited)
            best = node.best_child(total_visits, self.mcts_exploration)
            if best is None:
                break
            node = best
        return node

    def _simulate(
        self,
        node: MCTSNode,
        documents: list[dict[str, Any]],
        all_keywords: list[str],
    ) -> float:
        """Simulate a rollout from the node, returning relevance value.

        Computes keyword coverage of the node's keyword against documents.
        """
        if node is None:
            return 0.0

        # Count how many documents contain this keyword
        kw = node.keyword
        match_count = 0
        total = len(documents)
        for doc in documents:
            content = doc.get("content", doc.get("text", "")).lower()
            if kw in content:
                match_count += 1

        # Relevance = proportion of docs containing the keyword
        base_relevance = match_count / max(total, 1)

        # Bonus for keyword diversity in the path from root
        path_kws: set[str] = set()
        n: MCTSNode | None = node
        while n is not None:
            path_kws.add(n.keyword)
            n = n.parent
        diversity_bonus = len(path_kws) / max(len(all_keywords), 1) * 0.1

        return min(1.0, base_relevance + diversity_bonus)

    def _backpropagate(self, node: MCTSNode, value: float) -> None:
        """Propagate simulation value up the tree."""
        n: MCTSNode | None = node
        while n is not None:
            n.visits += 1
            n.total_value += value
            n = n.parent

    def _score_documents_by_mcts(
        self,
        root: MCTSNode,
        keywords: list[str],
        documents: list[dict[str, Any]],
    ) -> list[tuple[float, dict[str, Any]]]:
        """Score each document using MCTS node visit frequencies."""
        # Collect node visits per keyword
        kw_visits: dict[str, int] = {}
        self._collect_visits(root, kw_visits)

        total_visits = sum(kw_visits.values()) or 1

        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in documents:
            content = doc.get("content", doc.get("text", "")).lower()
            score = 0.0
            for kw, visits in kw_visits.items():
                if kw in content:
                    # Weight by visit proportion
                    score += visits / total_visits
            scored.append((score, doc))

        return scored

    def _collect_visits(
        self,
        node: MCTSNode,
        kw_visits: dict[str, int],
    ) -> None:
        """Recursively collect visit counts per keyword."""
        kw_visits[node.keyword] = kw_visits.get(node.keyword, 0) + node.visits
        for child in node.children:
            self._collect_visits(child, kw_visits)

    @staticmethod
    def _count_nodes(node: MCTSNode) -> int:
        """Count total nodes in the MCTS tree."""
        count = 1
        for child in node.children:
            count += MCTSRetriever._count_nodes(child)
        return count

    # ------------------------------------------------------------------
    # Synthetic KB generation (for testing / fallback)
    # ------------------------------------------------------------------

    @staticmethod
    def _make_synthetic_kb(
        kb_size: int,
        keywords: list[str],
    ) -> list[dict[str, str]]:
        """Generate synthetic documents for test/demo purposes."""
        import hashlib
        import random as _rnd

        _rng = _rnd.Random(42)

        docs: list[dict[str, str]] = []
        for i in range(kb_size):
            # Mix some keywords into each doc
            doc_keywords = keywords[: _rng.randint(1, 5)] if keywords else []
            content = (
                f"This is document {i}. "
                + " ".join(doc_keywords)
                + f" Additional content about topic {i} for diversity."
            )
            title = f"Doc {i}: {' '.join(doc_keywords[:2])}" if doc_keywords else f"Doc {i}"
            doc_id = hashlib.md5(f"synthetic_{i}".encode()).hexdigest()[:12]
            docs.append({"id": doc_id, "title": title, "content": content})
        return docs
