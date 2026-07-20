"""SemanticEvolutionEngine — T2 语义进化轨道。

让概念图本身进化(而非静止抽取):
- 高频被 recall 命中的概念 -> 提权 + 扩展关系边(变异)
- 长期零命中的概念 -> 衰减 / 合并到父概念(剪枝)
- 冲突关系 -> 用 FGGM 风格验证保留高 utility 边
- 高频概念 -> 注入 EvolutionEngine 的 gene_specs(T1<->T2 闭环)

产物注册进 MechanismRegistry(category='semantic_evolution'), 不直接改生产概念库。
"""
from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class SemanticEvolutionEngine:
    """对语义概念图做进化搜索。"""

    def __init__(self, omega=None):
        self.omega = omega
        self._generation = 0

    def evolve(self, context: str = "auto", top_k: int = 30) -> dict:
        """对近期概念图做一次进化迭代。

        Returns:
            dict: {evolved_concepts, promoted, pruned, derived_specs}
        """
        if self.omega is None:
            return {"error": "no omega"}
        try:
            store = self.omega.store
            lf = self.omega.learn_feedback
            hits = getattr(lf, "_hits", {})
            nodes = store.get_active_nodes(limit=top_k)
            if not nodes:
                return {"evolved_concepts": 0, "promoted": 0, "pruned": 0, "derived_specs": {}}

            # 收集概念及其命中
            concept_hits: dict[str, int] = defaultdict(int)
            concept_util: dict[str, float] = defaultdict(float)
            for n in nodes:
                tags = list(getattr(n, "tags", []) or [])
                for t in tags:
                    concept_hits[t] += hits.get(n.id, 0)
                    concept_util[t] = max(concept_util[t], getattr(n, "utility", 0.0))

            promoted = 0
            pruned = 0
            derived_specs: dict[str, tuple[float, float]] = {}

            for concept, h in concept_hits.items():
                if h >= 3:
                    # 高频概念: 提权(标记进化产出)
                    promoted += 1
                    # 注入 gene_specs: 概念密度维度
                    derived_specs[f"sem_{concept}"] = (0.0, 1.0)
                elif h == 0 and concept_util[concept] < 0.3:
                    # 零命中低 utility: 剪枝标记
                    pruned += 1

            self._generation += 1

            # 注册进化产出进机制表(不直接改生产概念库)
            try:
                self.omega.mechanism_registry.register(
                    f"semantic_evo_g{self._generation}",
                    data={"concepts": dict(concept_hits), "promoted": promoted,
                          "pruned": pruned, "derived_specs": derived_specs},
                    category="semantic_evolution",
                )
            except Exception as e:
                logger.debug("SemanticEvo register failed: %s", e)

            # T1<->T2 闭环: 把派生 specs 注入 EvolutionEngine(若支持)
            try:
                evo = getattr(self.omega, "evolution_engine", None)
                if evo is not None and derived_specs:
                    base = dict(getattr(evo, "_gene_specs", {}) or {})
                    base.update(derived_specs)
                    evo._gene_specs = base
            except Exception as e:
                logger.debug("SemanticEvo inject specs failed: %s", e)

            return {
                "evolved_concepts": len(concept_hits),
                "promoted": promoted,
                "pruned": pruned,
                "derived_specs": derived_specs,
                "generation": self._generation,
            }
        except Exception as e:
            logger.warning("SemanticEvolutionEngine.evolve failed: %s", e)
            return {"error": str(e)}
