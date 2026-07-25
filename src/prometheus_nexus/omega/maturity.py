"""omega 包 — 系统成熟度多维度评分逻辑外置.

真拆 life.py 第七步(最高收益高风险项, 用户授权):
把 Omega._compute_fitness(5007-5095) 纯搬迁到 omega/maturity.py。
10 维度质量评分(记忆丰富度/多样性/进化/健康/HarnessX/Utility/热力学/
多类型覆盖/机制消费率/反刍产出率), 与调度解耦, 可外置收敛上帝类。

纯搬迁, 行为逐行不变(含写 self._last_fitness_detail 三维分解)。
"""

from __future__ import annotations

import logging

from prometheus_nexus.foundation.schema import NodeType

logger = logging.getLogger(__name__)


def compute_fitness(self) -> float:
    """Compute system fitness based on multiple quality dimensions.

    返回 0-1 综合成熟度分; 同时写 self._last_fitness_detail(三维分解供 dashboard).
    (原 Omega._compute_fitness 的纯搬迁版本, 行为逐行不变)
    """
    # Dimension 1: Memory richness (0-0.3)
    node_count = self.store.get_node_count()
    edge_count = self.store.get_edge_count()
    memory_score = min(0.3, (node_count * 0.0005 + edge_count * 0.0003))

    # Dimension 2: Diversity (0-0.2)
    types = set()
    nodes = self.store.get_active_nodes(limit=200)
    for n in nodes:
        types.add(n.type.value if hasattr(n.type, "value") else str(n.type))
    diversity_score = min(0.2, len(types) * 0.04)

    # Dimension 3: Evolution activity (0-0.2)
    evo_stats = self.evolution_engine.get_stats()
    evo_score = min(0.2, evo_stats.get("generations", 0) * 0.02)

    # Dimension 4: System health (0-0.15)
    health_map = {"healthy": 0.15, "degraded": 0.08, "critical": 0.02, "empty": 0.0}
    health_score = health_map.get(self._compute_health(), 0.0)

    # Dimension 5: HarnessX evolution (0-0.15)
    harness_stats = self.harness_x.get_stats()
    harness_score = min(0.15, harness_stats.get("evolutions", 0) * 0.05)

    # Dimension 6: Utility health (0-0.1)
    util_stats = self.utility_tracker.get_stats()
    util_score = min(0.1, util_stats.get("avg_utility", 0.5) * 0.1)

    # Dimension 7: Thermodynamic energy (0-0.1)
    ti_energy = self.thermodynamic.get_energy()
    energy_score = min(0.1, ti_energy * 0.1)

    # Dimension 8: 多类型覆盖度 (0-0.1)
    try:
        type_counts = {}
        for nt in [NodeType.FACT, NodeType.CONCEPT, NodeType.PROCEDURE,
                   NodeType.PAPER, NodeType.PROJECT, NodeType.SKILL,
                   NodeType.PATTERN]:
            c = self.store.get_nodes_by_type(nt, limit=100000)
            if isinstance(c, (list, tuple)):
                type_counts[nt.value] = len(c)
            elif isinstance(c, int):
                type_counts[nt.value] = c
        non_empty = sum(1 for v in type_counts.values() if v > 0)
        multitype_score = min(0.1, non_empty * 0.02)
    except Exception:
        multitype_score = 0.0

    # Dimension 9: 机制消费率 (0-0.1) — 方案Y: 覆盖全 6 类机制载体
    try:
        snap = self.get_mechanism_consumption()
        total_all = max(1, snap["total"])
        consumed_all = snap["consumed"]
        consumption_score = min(0.1, consumed_all / total_all * 0.1)
    except Exception:
        consumption_score = 0.0

    # Dimension 10: 反刍产出率 (0-0.1)
    try:
        hist = getattr(self.knowledge_rumination, "history", [])
        recent = hist[-1] if hist else None
        rumination_score = 0.0
        if recent is not None:
            promoted = getattr(recent, "skills_promoted", 0) or 0
            routed = getattr(recent, "routed_nodes", 0) or 0
            rumination_score = min(0.1, (promoted + routed) / 20.0)
    except Exception:
        rumination_score = 0.0

    total = (memory_score + diversity_score + evo_score + health_score
             + harness_score + util_score + energy_score
             + multitype_score + consumption_score + rumination_score)
    # 暴露三维分解, 供 dashboard_summary / 监控脚本读取(B1 产出可见性)
    self._last_fitness_detail = {
        "total": round(min(1.0, max(0.0, total)), 4),
        "memory": round(memory_score, 4),
        "diversity": round(diversity_score, 4),
        "evolution": round(evo_score, 4),
        "health": round(health_score, 4),
        "harness": round(harness_score, 4),
        "utility": round(util_score, 4),
        "energy": round(energy_score, 4),
        "multitype": round(multitype_score, 4),
        "consumption": round(consumption_score, 4),
        "rumination": round(rumination_score, 4),
    }
    return min(1.0, max(0.0, total))
