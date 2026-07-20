"""MemoryGravity — Gravity-based memory importance model.

基于:
- "Gravity Model for Urban Interactions" (Simon & Nijkamp, 1972) + Omega记忆系统
  - 引力计算: g(n1,n2) = mass(n1)×mass(n2) / max(|mass(n1)-mass(n2)|, ε)
  - 质量=utility/importance, 节点越重要引力越大
  - ε防除零: 最小分母保护

算法:
    compute(n1, n2):
        1. 获取节点质量(mass)
        2. 引力 = m1*m2 / max(|m1-m2|, ε)

    get_strongest_pair():
        1. 遍历所有节点对O(N²)
        2. 返回引力最大的对

    rank_by_gravity(reference):
        1. 计算reference到所有节点的引力
        2. 按引力降序排列

来源: Omega系统 gravity 记忆重要性模型
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)



class MemoryGravity:
    """Gravity-based memory importance.

    Usage:
        g = MemoryGravity(epsilon=0.01)
        g.add_node("n1", mass=0.9)
        g.add_node("n2", mass=0.3)
        g.add_node("n3", mass=0.7)

        strength = g.compute("n1", "n2")
        strongest = g.get_strongest_pair()
        ranked = g.rank_by_gravity("n1")
    """

    def __init__(self, epsilon: float = 0.01):
        """Initialize memory gravity.

        Args:
            epsilon: Small constant to prevent division by zero.
        """
        self._epsilon = epsilon
        self._nodes: dict[str, float] = {}

    def add_node(self, node_id: str, mass: float = 1.0) -> None:
        """Add or update a node's mass.

        Args:
            node_id: Node identifier.
            mass: Node mass (importance) [0, ∞).
        """
        self._nodes[node_id] = max(0.01, mass)

    def compute(self, n1: str, n2: str) -> float:
        """Compute gravitational force between two nodes.

        Args:
            n1: First node ID.
            n2: Second node ID.

        Returns:
            Gravitational strength [0, ∞).
        """
        m1 = self._nodes.get(n1, 0.1)
        m2 = self._nodes.get(n2, 0.1)
        return (m1 * m2) / max(abs(m1 - m2), self._epsilon)

    def get_strongest_pair(self) -> tuple[str, str, float] | None:
        """Find the pair of nodes with strongest gravitational pull."""
        if len(self._nodes) < 2:
            return None
        best = (None, None, 0.0)
        ids = list(self._nodes.keys())
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                s = self.compute(ids[i], ids[j])
                if s > best[2]:
                    best = (ids[i], ids[j], s)
        return best if best[0] else None

    def rank_by_gravity(self, reference: str) -> list[dict]:
        """Rank all nodes by gravitational pull to a reference node."""
        if reference not in self._nodes:
            return []
        scored = []
        for nid, mass in self._nodes.items():
            if nid != reference:
                gravity = self.compute(reference, nid)
                scored.append({"node_id": nid, "gravity": gravity, "mass": mass})
        scored.sort(key=lambda x: x["gravity"], reverse=True)
        return scored

    def get_total_gravity(self) -> float:
        """Sum of all pairwise gravitational forces."""
        ids = list(self._nodes.keys())
        total = 0.0
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                total += self.compute(ids[i], ids[j])
        return total

    def get_stats(self) -> dict:
        masses = list(self._nodes.values())
        return {
            "nodes": len(self._nodes),
            "avg_mass": sum(masses) / max(len(masses), 1),
            "total_gravity": self.get_total_gravity(),
        }
