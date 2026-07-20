"""HebbianMemory — Hebbian edge-weight learning with hub-driven consolidation.

Based on HeLa-Mem (arXiv 2604.16839):
  Three bio-inspired memory mechanisms: association, consolidation,
  spreading activation. Hub-driven consolidation (not time/similarity).

Hebbian principle: edges that fire together wire together.
Consolidation is driven by hub nodes (high-degree nodes in the knowledge graph),
not by time or similarity.

Architecture:
    - Maintains an edge weight matrix keyed by sorted (source, target) tuples
    - update_edge() strengthens weights on co-retrieval (Hebbian plasticity)
    - find_hubs() ranks nodes by degree × avg edge weight (hub centrality)
    - should_consolidate() identifies nodes connected to hub nodes
    - activate() spreads activation through graph (paper's third mechanism)

Thread Safety:
    Uses threading.Lock for all mutable operations.

Usage:
    hm = HebbianMemory()
    hm.update_edge("node_a", "node_b", delta_weight=0.05)
    hm.update_edge("node_a", "node_c", delta_weight=0.05)

    hubs = hm.find_hubs(top_k=5)
    # hubs = [("node_a", 0.10), ...]

    if hm.should_consolidate("node_b"):
        print("node_b is a consolidation candidate")
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class HebbianMemory:
    """Hebbian edge-weight learning with hub-driven consolidation.

    Attributes:
        _edges: dict[tuple[str, str], dict] — edge data keyed by sorted (u, v).
            Each value has: weight, relation, created_at, update_count.
        _lock: threading.Lock for thread-safe mutations.
    """

    def __init__(self) -> None:
        self._edges: dict[tuple[str, str], dict[str, Any]] = {}
        # RLock: get_stats() holds the lock then calls find_hubs() which
        # also acquires it -> a plain Lock would deadlock on re-entry.
        self._lock = threading.RLock()

    # ============================================================
    # Hebbian update
    # ============================================================

    def update_edge(
        self,
        source_id: str,
        target_id: str,
        delta_weight: float = 0.05,
        relation: str = "hebbian",
    ) -> None:
        """Hebbian update: strengthen the edge between two nodes.

        When two nodes are retrieved or activated together, increase the
        edge weight between them.  Edges that fire together wire together.

        Args:
            source_id: First node ID.
            target_id: Second node ID.
            delta_weight: Amount to add to the edge weight (default 0.05).
            relation: Relationship label (default "hebbian").

        Complexity: O(1).
        """
        if source_id == target_id:
            return  # no self-loops

        key: tuple[str, str] = tuple(sorted([source_id, target_id]))

        with self._lock:
            if key in self._edges:
                entry = self._edges[key]
                entry["weight"] = min(1.0, entry["weight"] + delta_weight)
                entry["update_count"] += 1
                logger.debug(
                    "Hebbian edge %s<->%s strengthened to %.3f (updates=%d)",
                    key[0][:8],
                    key[1][:8],
                    entry["weight"],
                    entry["update_count"],
                )
            else:
                self._edges[key] = {
                    "weight": min(1.0, delta_weight),
                    "relation": relation,
                    "created_at": time.time(),
                    "update_count": 1,
                }
                logger.debug(
                    "Hebbian edge %s<->%s created with weight %.3f",
                    key[0][:8],
                    key[1][:8],
                    delta_weight,
                )

    def decay_edge(
        self,
        source_id: str,
        target_id: str,
        decay_factor: float = 0.95,
        min_weight: float = 0.01,
    ) -> None:
        """Decay an edge weight (e.g., when nodes are rarely accessed together).

        Args:
            source_id: First node ID.
            target_id: Second node ID.
            decay_factor: Multiplicative decay factor (default 0.95).
            min_weight: Floor weight below which the edge is pruned (default 0.01).
        """
        if source_id == target_id:
            return

        key: tuple[str, str] = tuple(sorted([source_id, target_id]))

        with self._lock:
            if key not in self._edges:
                return
            entry = self._edges[key]
            new_weight = entry["weight"] * decay_factor
            if new_weight < min_weight:
                del self._edges[key]
                logger.debug(
                    "Hebbian edge %s<->%s pruned (weight %.4f < %.4f)",
                    key[0][:8],
                    key[1][:8],
                    new_weight,
                    min_weight,
                )
            else:
                entry["weight"] = new_weight

    # ============================================================
    # Spreading activation (HeLa-Mem third mechanism)
    # ============================================================

    def activate(self, node_id: str, decay_factor: float = 0.5,
                 max_depth: int = 3) -> dict[str, float]:
        """Spread activation through the graph from a source node.

        When node(i) is activated, activation propagates to neighbors
        with exponential decay. Core HeLa-Mem mechanism.

        Args:
            node_id: Source node ID.
            decay_factor: Per-hop decay (default 0.5).
            max_depth: Max propagation depth (default 3).

        Returns:
            {node_id: activation_level}.
        """
        activation: dict[str, float] = {node_id: 1.0}
        frontier: set[str] = {node_id}
        depth = 0
        while frontier and depth < max_depth:
            depth += 1
            next_frontier: set[str] = set()
            for current in frontier:
                current_act = activation.get(current, 0.0)
                if current_act <= 0:
                    continue
                with self._lock:
                    neighbors: list[str] = []
                    for (u, v) in self._edges:
                        if u == current:
                            neighbors.append(v)
                        elif v == current:
                            neighbors.append(u)
                for neighbor in neighbors:
                    propagated = current_act * decay_factor
                    existing = activation.get(neighbor, 0.0)
                    new_val = max(existing, propagated)
                    if abs(new_val - existing) > 0.01:
                        activation[neighbor] = new_val
                        next_frontier.add(neighbor)
            frontier = next_frontier
        return activation

    # ============================================================
    # Hub detection
    # ============================================================

    def find_hubs(self, top_k: int = 10) -> list[tuple[str, float]]:
        """Find hub nodes by graph centrality.

        Hub score = sum of edge weights incident to the node
        (degree × average edge weight implicitly).

        Returns:
            List of (node_id, hub_score) sorted descending by score.

        Complexity: O(E + D log D) where E = edges, D = distinct nodes.
        """
        score: dict[str, float] = defaultdict(float)

        with self._lock:
            for (u, v), data in self._edges.items():
                w = data["weight"]
                score[u] += w
                score[v] += w

        sorted_hubs = sorted(score.items(), key=lambda x: x[1], reverse=True)
        return sorted_hubs[:top_k]

    # ============================================================
    # Consolidation candidates
    # ============================================================

    def should_consolidate(
        self,
        node_id: str,
        hub_degree_threshold: float = 3.0,
    ) -> bool:
        """Determine whether a node is a consolidation candidate.

        A node should be consolidated if it is connected to hub nodes
        (high cumulative edge weight), indicating structural importance
        in the knowledge graph.

        Args:
            node_id: The node to check.
            hub_degree_threshold: Minimum cumulative edge weight for
                consolidation (default 3.0).

        Returns:
            True if the node is a consolidation candidate.

        Complexity: O(E) in the worst case.
        """
        cumulative_weight = 0.0

        with self._lock:
            for (u, v), data in self._edges.items():
                if u == node_id or v == node_id:
                    cumulative_weight += data["weight"]
                    if cumulative_weight >= hub_degree_threshold:
                        return True

        return cumulative_weight >= hub_degree_threshold

    def get_consolidation_candidates(
        self,
        min_hub_score: float = 1.0,
        top_k: int = 50,
    ) -> list[str]:
        """Get all nodes eligible for consolidation.

        Args:
            min_hub_score: Minimum hub score to be a candidate.
            top_k: Maximum number of candidates to return.

        Returns:
            List of node IDs sorted by hub score descending.
        """
        all_hubs = self.find_hubs(top_k=top_k * 2)
        candidates = [
            node_id
            for node_id, score in all_hubs
            if score >= min_hub_score
        ]
        return candidates[:top_k]

    def get_edge_weight(self, source_id: str, target_id: str) -> float:
        """Get the Hebbian weight between two nodes.

        Args:
            source_id: First node ID.
            target_id: Second node ID.

        Returns:
            Edge weight, or 0.0 if no edge exists.
        """
        key: tuple[str, str] = tuple(sorted([source_id, target_id]))
        with self._lock:
            entry = self._edges.get(key)
            return entry["weight"] if entry else 0.0

    # ============================================================
    # Statistics
    # ============================================================

    def get_stats(self) -> dict[str, Any]:
        """Get Hebbian memory statistics.

        Returns:
            Dictionary with total_edges, unique_nodes, average_weight,
            hub_count (top 5), etc.
        """
        with self._lock:
            total_edges = len(self._edges)
            if total_edges == 0:
                return {
                    "total_edges": 0,
                    "unique_nodes": 0,
                    "avg_weight": 0.0,
                    "max_weight": 0.0,
                    "hub_count": 0,
                    "top_hubs": [],
                }

            nodes: set[str] = set()
            total_weight = 0.0
            max_weight = 0.0
            for (u, v), data in self._edges.items():
                nodes.add(u)
                nodes.add(v)
                w = data["weight"]
                total_weight += w
                if w > max_weight:
                    max_weight = w

            hubs = self.find_hubs(top_k=5)

            return {
                "total_edges": total_edges,
                "unique_nodes": len(nodes),
                "avg_weight": total_weight / total_edges,
                "max_weight": max_weight,
                "hub_count": len(hubs),
                "top_hubs": [{"node_id": n, "score": round(s, 4)} for n, s in hubs],
            }
