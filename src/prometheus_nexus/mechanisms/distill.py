"""distill — SEED 蒸馏奖励计算(架构优化: 从 life.py 外置纯函数器官).

外置动机
--------
life.py 的 _distill_bonus(1208-1221) 核心计算是纯函数:
  bonus = ALPHA * log1p(n_seen)
其中 n_seen = len(hindsight_miner._seen)。本不属于上帝调度流程,
是可外置并单测的器官。

按"保留上帝调度权、外置器官"原则:
- distill_bonus(n_seen, alpha=0.02) -> float: 纯计算外置。
- life.py._distill_bonus 改为: 取 n_seen → 调 distill_bonus, 行为逐行不变。
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

DEFAULT_ALPHA = 0.02


def distill_bonus(n_seen: int, alpha: float = DEFAULT_ALPHA) -> float:
    """SEED 稠密蒸馏奖励: 已提炼可复用技能数 → 行为效应奖励.

    Args:
        n_seen: 已见过的 hindsight 技能数
        alpha: 缩放系数(默认 0.02)

    Returns:
        float: alpha * log1p(n_seen); n_seen<=0 时返回 0.0
    """
    if n_seen <= 0:
        return 0.0
    return alpha * math.log1p(n_seen)


__all__ = ["distill_bonus", "DEFAULT_ALPHA"]
