"""SelectionGate — 影子 A/B 选择门(Phase 0 共享脊柱).

问题实证:
- T3/T4 机制 mount_dynamic 后 pending=False -> 可能直接 active -> 空壳被 invoke,
  但从不与 base 对比"谁更有效". 进化需要"变异->执行->评估->选择", 当前缺"选择".

设计:
- 候选机制进 candidate(pending) 状态, 不直替 base.
- 影子 A/B: candidate vs base 并行跑固定 probe 集, 累计 effect.
- effect_candidate > effect_base + margin -> promote(active); 持续 <= -> prune.
- 决策可持久化(由 EvolutionState 或调用方负责).
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class SelectionGate:
    """影子 A/B 选择门: candidate 不直替, 与 base 对比 effect, 优则 promote."""

    def __init__(self, margin: float = 0.05, min_samples: int = 5, prune_below: float = -0.1):
        self.margin = margin
        self.min_samples = min_samples
        self.prune_below = prune_below
        # name -> [(cand_effect, base_effect), ...]
        self._samples: dict[str, list[tuple[float, float]]] = {}

    def observe(self, name: str, cand_effect: float, base_effect: float) -> str:
        """记录一次对比, 返回决策: 'promote' | 'prune' | 'hold'.

        promote/prune 是建议, 由调用方(nexus/life)执行状态变更 + 持久化.
        """
        buf = self._samples.setdefault(name, [])
        buf.append((float(cand_effect), float(base_effect)))
        if len(buf) < self.min_samples:
            return "hold"
        cand_avg = sum(c for c, _ in buf) / len(buf)
        base_avg = sum(b for _, b in buf) / len(buf)
        if cand_avg > base_avg + self.margin:
            return "promote"
        if cand_avg < self.prune_below or cand_avg <= base_avg - self.margin:
            return "prune"
        return "hold"

    def decision_for(self, name: str) -> str:
        """仅查询当前决策(不新增样本), 用于重启后恢复/外部查询."""
        buf = self._samples.get(name)
        if not buf or len(buf) < self.min_samples:
            return "hold"
        cand_avg = sum(c for c, _ in buf) / len(buf)
        base_avg = sum(b for _, b in buf) / len(buf)
        if cand_avg > base_avg + self.margin:
            return "promote"
        if cand_avg < self.prune_below or cand_avg <= base_avg - self.margin:
            return "prune"
        return "hold"

    def serialize(self) -> dict:
        return {
            "margin": self.margin,
            "min_samples": self.min_samples,
            "prune_below": self.prune_below,
            "samples": self._samples,
        }

    @classmethod
    def deserialize(cls, data: dict) -> "SelectionGate":
        g = cls(
            margin=data.get("margin", 0.05),
            min_samples=data.get("min_samples", 5),
            prune_below=data.get("prune_below", -0.1),
        )
        g._samples = data.get("samples", {})
        return g
