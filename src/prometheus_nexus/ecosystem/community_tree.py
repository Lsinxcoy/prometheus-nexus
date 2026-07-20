"""CommunityTree — Community-based skill organization with real graph algorithms.

基于:
- Blondel et al. (2008) "Fast Unfolding of Community Structure in Large Networks" (Louvain方法)
  - 模块化优化: 贪婪模量优化, 逐节点尝试移至邻居社区
  - modularity_gain: ΔQ = (σ_in/m2) - (σ_tot×k_i)/(2×m2²)
  - Jaccard相似度: 节点间边权重基于属性重叠度
  - 社区检测迭代: 直到无模块增益改进

算法:
    find_communities():
        1. 每节点初始为独立社区
        2. 对每节点: 计算移至邻居社区的modularity_gain
        3. 增益>0 → 移动, 重复直到收敛

来源: Omega系统 community_tree 社区检测技能组织模块 + Louvain算法
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import math
from collections import defaultdict


class CommunityTree:
    """Community-based skill organization with modularity-driven detection.

    Algorithm:
        1. Build an adjacency graph from the tree structure
        2. Compute edge weights from shared data attributes
        3. Detect communities via greedy modularity optimization (Louvain-like)
        4. Track community statistics and evolution

    Usage:
        tree = CommunityTree()
        tree.add_child(None, {"skill": "python", "domain": "coding"})
        tree.add_child(None, {"skill": "analysis", "domain": "research"})
        communities = tree.find_communities()
    """

    def __init__(self):
        self._tree: dict[str, list[str]] = {"root": []}
        self._node_data: dict[str, dict] = {}
        self._edges: list[tuple[str, str, float]] = []
        self._community_history: list[dict] = []

    def add_child(self, parent: str | None, data: dict | None = None):
        parent = parent or "root"
        node_id = f"node_{len(self._node_data)}"
        self._tree.setdefault(parent, []).append(node_id)
        self._tree.setdefault(node_id, [])
        self._node_data[node_id] = data or {}

        if parent and parent in self._node_data:
            weight = self._compute_similarity(self._node_data[parent], data or {})
            self._edges.append((parent, node_id, weight))

    def _compute_similarity(self, a: dict, b: dict) -> float:
        """Compute Jaccard similarity between two node data dicts."""
        set_a = set()
        set_b = set()
        for k, v in a.items():
            if isinstance(v, str):
                set_a.add(f"{k}:{v}")
            elif isinstance(v, (list, tuple)):
                for item in v:
                    set_a.add(f"{k}:{item}")
        for k, v in b.items():
            if isinstance(v, str):
                set_b.add(f"{k}:{v}")
            elif isinstance(v, (list, tuple)):
                for item in v:
                    set_b.add(f"{k}:{item}")
        if not set_a and not set_b:
            return 0.3
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / max(len(union), 1)

    def find_communities(self) -> list[list[str]]:
        """Detect communities via greedy modularity optimization.

        Louvain-like algorithm:
        1. Start: each node is its own community
        2. Iterate: move node to neighbor's community if modularity increases
        3. Repeat until no improvement
        """
        nodes = list(self._node_data.keys())
        if len(nodes) <= 1:
            return []

        adjacency = defaultdict(list)
        edge_weights = defaultdict(float)
        for src, dst, w in self._edges:
            adjacency[src].append(dst)
            adjacency[dst].append(src)
            edge_weights[(src, dst)] = w
            edge_weights[(dst, src)] = w

        total_weight = sum(w for _, _, w in self._edges) or 1.0

        community_of = {n: n for n in nodes}
        degrees = {n: sum(edge_weights.get((n, nb), 0.3) for nb in adjacency.get(n, [])) for n in nodes}

        improved = True
        while improved:
            improved = False
            for node in nodes:
                current_comm = community_of[node]
                best_comm = current_comm
                best_gain = 0.0

                neighbor_comms = set()
                for nb in adjacency.get(node, []):
                    neighbor_comms.add(community_of[nb])

                for comm in neighbor_comms:
                    if comm == current_comm:
                        continue
                    gain = self._modularity_gain(node, comm, community_of, edge_weights, degrees, total_weight)
                    if gain > best_gain:
                        best_gain = gain
                        best_comm = comm

                if best_comm != current_comm:
                    community_of[node] = best_comm
                    improved = True

        communities_map: dict[str, list[str]] = defaultdict(list)
        for node, comm in community_of.items():
            communities_map[comm].append(node)

        communities = [members for members in communities_map.values() if len(members) > 1]

        self._community_history.append({
            "count": len(communities),
            "sizes": [len(c) for c in communities],
            "timestamp": len(self._community_history),
        })

        return communities

    def _modularity_gain(self, node: str, target_comm: str, community_of: dict,
                         edge_weights: dict, degrees: dict, total_weight: float) -> float:
        """Compute modularity gain from moving node to target community."""
        sigma_in = 0.0
        sigma_tot = 0.0
        k_i = degrees.get(node, 0.0)

        for n2, comm2 in community_of.items():
            if comm2 == target_comm:
                sigma_tot += degrees.get(n2, 0.0)
                w = edge_weights.get((node, n2), 0.0)
                if w > 0:
                    sigma_in += w

        m2 = max(total_weight, 1e-9)
        gain = (sigma_in / m2) - (sigma_tot * k_i) / (2.0 * m2 * m2)
        return gain

    def get_community_stats(self) -> dict:
        communities = self.find_communities()
        if not communities:
            return {"count": 0, "avg_size": 0, "largest": 0}
        sizes = [len(c) for c in communities]
        return {
            "count": len(communities),
            "avg_size": sum(sizes) / len(sizes),
            "largest": max(sizes),
            "smallest": min(sizes),
        }

    def get_stats(self) -> dict:
        return {
            "nodes": len(self._node_data),
            "edges": len(self._edges),
            "communities": len(self.find_communities()),
            "history": len(self._community_history),
        }
