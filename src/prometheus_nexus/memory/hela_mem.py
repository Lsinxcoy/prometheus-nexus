"""HeLaMem — Hebbian Learning and Associative Memory (HeLa-Mem).

Based on arXiv 2604.16839:
  SOTA on LoCoMo benchmark. Three bio-inspired mechanisms:
  1. Association: Hebbian edge weights emerge from co-activation patterns
  2. Consolidation: Hub nodes (densely connected) determine consolidation targets
  3. Spreading activation: Activation propagates through graph edges

Architecture:
  - Weighted undirected graph: nodes = memory items, edges = co-activation.
  - Hebbian update: w_ij += η · act(i) · act(j) when two nodes fire together.
  - Hub detection via degree centrality (sum of incident edge weights).
  - **Spreading activation**: when node i is activated, propagate 50% to neighbors.
  - Consolidation targeting based on topological hub membership, not recency.

Thread safety:
  Uses threading.Lock for all mutable operations.

Usage:
    mem = HeLaMem(eta=0.1)
    mem.observe_access("node_a", "node_b")   # strengthens edge
    mem.activate("node_a")                    # spreading activation
    hubs = mem.get_hub_nodes(top_k=5)         # [(node_id, score), ...]
    clusters = mem.hela_consolidate()         # {hub: [neighbors]}
    for u, v, w in mem.get_edges("node_a"):
        print(f"{u} --{w:.2f}--> {v}")
    stats = mem.get_stats()
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class HeLaMem:
    """Hebbian Learning and Associative Memory.

    Weighted undirected graph where:
      - nodes = memory items / concepts
      - edges = co-activation frequency (Hebbian weight)

    Hebbian plasticity:
        w_ij += η · act(i) · act(j)
    where act(i) is 1 when node i is accessed.

    Hub detection uses degree centrality (sum-of-incident-weights), which is
    the correct topologically-principled measure — not recency or similarity.
    """

    def __init__(self, eta: float = 0.1) -> None:
        """Initialise an empty HeLa-Mem graph.

        Args:
            eta: Hebbian learning rate — amount added to an edge each time
                its two endpoints are co-accessed (default 0.1, capped at 1.0).
        """
        self._eta = eta
        self._edges: dict[tuple[str, str], float] = {}  # (u,v) sorted -> weight
        # RLock: get_stats() holds the lock then calls get_hub_nodes()
        # which also acquires it -> plain Lock deadlocks on re-entry.
        self._lock = threading.RLock()

    # ---------------------------------------------------------------
    # Hebbian plasticity
    # ---------------------------------------------------------------

    def observe_access(self, node_i: str, node_j: str, decay: float = 0.0) -> None:
        """Record co-activation of two nodes and update their edge weight.

        Hebbian update:
            w_ij = min(1.0, w_ij + η)

        Self-loops (node_i == node_j) are silently ignored.

        Args:
            node_i: First node ID.
            node_j: Second node ID.
            decay: Optional decay amount (subtracted from all edges, default 0.0).
        """
        if node_i == node_j:
            return

        key: tuple[str, str] = tuple(sorted([node_i, node_j]))
        with self._lock:
            old = self._edges.get(key, 0.0)
            new = min(1.0, old + self._eta)
            self._edges[key] = new
            logger.debug(
                "HeLa edge %s<->%s weight %.3f -> %.3f",
                node_i[:8], node_j[:8], old, new,
            )
        # Apply global decay to simulate forgetting
        if decay > 0:
            with self._lock:
                for edge_key in list(self._edges.keys()):
                    w = self._edges[edge_key]
                    new_w = max(0.0, w - decay)
                    if new_w <= 0:
                        del self._edges[edge_key]
                    else:
                        self._edges[edge_key] = new_w

    # ---------------------------------------------------------------
    # Spreading activation (paper's third mechanism)
    # ---------------------------------------------------------------

    def activate(self, node_id: str, decay_factor: float = 0.5,
                 max_depth: int = 3) -> dict[str, float]:
        """Spread activation from a source node through the graph.

        When a node is activated, activation propagates to neighbors
        with exponential decay. This is the third core mechanism from
        HeLa-Mem (association, consolidation, spreading activation).

        Args:
            node_id: The initially activated node.
            decay_factor: Proportion of activation that passes each edge
                          (default 0.5 = 50% per hop).
            max_depth: Maximum propagation depth (default 3).

        Returns:
            {node_id: activation_level} for all activated nodes.
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
                # Find all neighbors
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

    # ---------------------------------------------------------------
    # Hub detection  (degree centrality)
    # ---------------------------------------------------------------

    def get_hub_nodes(self, top_k: int = 5) -> list[tuple[str, float]]:
        """Return top-k hub nodes ranked by degree centrality.

        Hub score = sum of weights of all edges incident to the node
        (equivalent to degree × average neighbour weight).

        Args:
            top_k: Number of top hubs to return (default 5).

        Returns:
            List of (node_id, hub_score) sorted descending by score.
        """
        scores: dict[str, float] = defaultdict(float)
        with self._lock:
            for (u, v), w in self._edges.items():
                scores[u] += w
                scores[v] += w

        sorted_hubs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_hubs[:top_k]

    # ---------------------------------------------------------------
    # Consolidation targeting  (topologically driven)
    # ---------------------------------------------------------------

    def hela_consolidate(self, top_k: int = 5) -> dict[str, list[str]]:
        """Identify hub nodes and return their neighbourhood for consolidation.

        The HeLa-Mem principle: consolidation targets are determined by a
        node's structural position in the graph (hub membership), NOT by
        recency-of-access or content-similarity.

        Returns a dict mapping each hub node ID to a list of neighbour node
        IDs that should be consolidated together with that hub.

        Args:
            top_k: How many top hubs to consider (default 5).

        Returns:
            {hub_node_id: [neighbour_id, ...], ...}
        """
        hubs = self.get_hub_nodes(top_k=top_k)
        hub_ids: set[str] = {h[0] for h in hubs}

        result: dict[str, list[str]] = {}
        with self._lock:
            for (u, v) in self._edges:
                if u in hub_ids:
                    result.setdefault(u, []).append(v)
                if v in hub_ids:
                    result.setdefault(v, []).append(u)

        # Deduplicate neighbours per hub
        for hub in result:
            result[hub] = list(set(result[hub]))

        return result

    # ---------------------------------------------------------------
    # Edge queries
    # ---------------------------------------------------------------

    def get_edges(self, node_id: str) -> list[tuple[str, str, float]]:
        """Return all edges incident to a node.

        Args:
            node_id: The node to query.

        Returns:
            List of (source, target, weight) tuples where source is always
            *this* node_id and target is the other endpoint.
        """
        results: list[tuple[str, str, float]] = []
        with self._lock:
            for (u, v), w in self._edges.items():
                if u == node_id:
                    results.append((u, v, w))
                elif v == node_id:
                    results.append((v, u, w))
        return results

    def get_edge_weight(self, node_i: str, node_j: str) -> float:
        """Get the Hebbian weight between two nodes.

        Args:
            node_i: First node ID.
            node_j: Second node ID.

        Returns:
            Edge weight, or 0.0 if no edge exists.
        """
        if node_i == node_j:
            return 0.0
        key: tuple[str, str] = tuple(sorted([node_i, node_j]))
        with self._lock:
            return self._edges.get(key, 0.0)

    # ---------------------------------------------------------------
    # Statistics
    # ---------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate graph statistics.

        Returns:
            Dictionary with keys:
              - total_edges: int
              - unique_nodes: int
              - avg_weight: float (mean edge weight)
              - top_hubs: list[{"node_id": str, "score": float}]
        """
        with self._lock:
            total_edges = len(self._edges)
            if total_edges == 0:
                return {
                    "total_edges": 0,
                    "unique_nodes": 0,
                    "avg_weight": 0.0,
                    "top_hubs": [],
                }

            nodes: set[str] = set()
            total_weight = 0.0
            for (u, v), w in self._edges.items():
                nodes.add(u)
                nodes.add(v)
                total_weight += w

            hubs = self.get_hub_nodes(top_k=5)

            return {
                "total_edges": total_edges,
                "unique_nodes": len(nodes),
                "avg_weight": round(total_weight / total_edges, 4),
                "top_hubs": [
                    {"node_id": n, "score": round(s, 4)} for n, s in hubs
                ],
            }
