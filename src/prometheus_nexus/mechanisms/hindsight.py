"""hindsight — 后见蒸馏轨迹拼装(架构优化: 从 life.py 外置纯函数器官).

外置动机
--------
life.py 的 _mine_hindsight(1182-1195) 含一段纯函数拼装: 从 errors/events/
produced/outcome/success 组装 trajectory 字典(供 _hindsight_miner.mine 输入)。
这段拼装不依赖 self 状态, 可外置并单测; mine/register 调用与异常隔离留在 life.py。

按"保留上帝调度权、外置器官"原则:
- build_hindsight_trajectory(errors, events, pipeline, produced, outcome, success)
  -> dict: 纯拼装, 无 self 依赖。
- life.py._mine_hindsight 改: 取 errors/events → 调 build_hindsight_trajectory →
  mine/register, 行为逐行不变。
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

logger = logging.getLogger(__name__)


def build_hindsight_trajectory(
    errors: Sequence[dict],
    events: Sequence[dict],
    pipeline: str,
    produced: int = 0,
    outcome: str = "",
    success: bool = True,
) -> dict:
    """组装后见蒸馏轨迹字典(供 HindsightMiner.mine 输入).

    Args:
        errors: 近期 issues(错误/警告)
        events: 近期事件总线事件
        pipeline: 当前管道名
        produced: 本管道产出数
        outcome: 结果描述
        success: 是否成功

    Returns:
        dict: {errors, events, diagnostics:{pipeline}, produced, outcome, success}
    """
    return {
        "errors": list(errors),
        "events": list(events),
        "diagnostics": {"pipeline": pipeline},
        "produced": produced,
        "outcome": outcome,
        "success": success,
    }


__all__ = ["build_hindsight_trajectory"]
