"""failure_stats — 失败日志统计器官(架构优化: 从 life.py 外置).

外置动机
--------
life.py 的 _collect_failure_paths / _get_failed_trajectory 都从 failure_log
取最近失败记录做映射/取首条。核心逻辑纯函数(输入 failures 列表, 输出 dict/list),
本不属于上帝调度流程, 可外置并单测。

按"保留上帝调度权、外置器官"原则:
- collect_failure_paths(failures, limit=10): 取含 action 的失败动作名
- get_failed_trajectory(failures, limit=5): 取最近一条失败轨迹, 无则空结构
- life.py 对应方法改为: 取 failures → 调本模块, 行为逐行不变。
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

logger = logging.getLogger(__name__)


def collect_failure_paths(failures: Sequence[dict], limit: int = 10) -> list[str]:
    """收集失败动作路径(供 ReflectiveSampler). 取含 action 的失败项."""
    return [f.get("action", "") for f in list(failures)[:limit] if f.get("action")]


def get_failed_trajectory(failures: Sequence[dict], limit: int = 5) -> dict:
    """取最近失败轨迹(供 L-ICL 纠正). 无失败返回空结构."""
    failures = list(failures)
    if failures:
        return failures[0]
    return {"trajectory": [], "state": {}}


__all__ = ["collect_failure_paths", "get_failed_trajectory"]
