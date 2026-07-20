"""ConsolidationPipeline — 4-stage memory consolidation pipeline.

基于:
- "Sleep-Dependent Memory Consolidation" (Diekelmann & Born, 2010)
  - 阶段1 Encode: 内容验证与标准化
  - 阶段2 Strengthen: 重要性阈值筛选(>0.3)
  - 阶段3 Integrate: 基于内容前缀去重
  - 阶段4 Prune: 移除弱记忆(<0.2)

算法:
    consolidate(items):
        Stage 1 (Encode): 过滤有内容的项
        Stage 2 (Strengthen): importance > 0.3
        Stage 3 (Integrate): dedup by content prefix[:50]
        Stage 4 (Prune): importance > 0.2 → 保留

来源: Omega系统 consolidation 四阶段管道 + lifecycle/consolidation_engine.py 实现
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)



class ConsolidationPipeline:
    """4-stage memory consolidation pipeline.

    Usage:
        pipeline = ConsolidationPipeline()
        pipeline.consolidate(items)
        stats = pipeline.get_stats()
    """

    def __init__(self):
        self._consolidated = 0
        self._stages_completed = 0
        self._stage_stats: dict[str, int] = {
            "encode": 0, "strengthen": 0, "integrate": 0, "prune": 0,
        }

    def consolidate(self, items: list | None = None) -> dict:
        """Run the 4-stage consolidation pipeline.

        Args:
            items: List of memory items (dicts with content, importance, etc.).

        Returns:
            Dict with stage results.
        """
        items = items or []

        # Stage 1: Encode
        encoded = [item for item in items if isinstance(item, dict) and item.get("content")]
        self._stage_stats["encode"] += len(encoded)

        # Stage 2: Strengthen
        strengthened = [item for item in encoded
                        if item.get("importance", item.get("utility", 0.5)) > 0.3]
        self._stage_stats["strengthen"] += len(strengthened)

        # Stage 3: Integrate (dedup by content prefix)
        integrated = []
        seen = set()
        for item in strengthened:
            key = item.get("content", "")[:50]
            if key not in seen:
                seen.add(key)
                integrated.append(item)
        self._stage_stats["integrate"] += len(integrated)

        # Stage 4: Prune
        pruned = []
        for item in integrated:
            if item.get("importance", item.get("utility", 0.5)) > 0.2:
                self._consolidated += 1
            else:
                pruned.append(item)
        self._stage_stats["prune"] += len(integrated) - len(pruned)

        self._stages_completed += 1

        return {
            "input_count": len(items),
            "encoded": len(encoded),
            "strengthened": len(strengthened),
            "integrated": len(integrated),
            "consolidated": len(integrated) - len(pruned),
            "pruned": len(pruned),
        }

    def get_stats(self) -> dict:
        return {
            "consolidated": self._consolidated,
            "stages_completed": self._stages_completed,
            "stage_stats": dict(self._stage_stats),
        }
