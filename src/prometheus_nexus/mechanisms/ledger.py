"""ledger — 产出/问题账本纯逻辑器官(架构优化: 从 life.py 外置).

外置动机
--------
life.py 的 record_production(去重判断段)与 _get_issues 含两段纯逻辑:
- 去重: 检查最近 N 条产出是否已记相同 key(避免多路径重复记账)
- issues 统计: 按时间窗过滤 + 按 level 计数

这两段纯函数(输入列表 → 输出 bool/dict)本不属于上帝调度流程,
可外置并单测。写入/锁仍留在 life.py(状态变更属上帝职责)。

按"保留上帝调度权、外置器官"原则:
- is_duplicate_production(productions, ptype, summary, detail, window=200)
- summarize_issues(issues, since_minutes=30)
- life.py 对应逻辑改委托调用, 行为逐行不变。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Sequence

logger = logging.getLogger(__name__)


def is_duplicate_production(
    productions: Sequence[dict],
    ptype: str,
    summary: str,
    detail: dict | None = None,
    window: int = 200,
) -> bool:
    """判断最近 window 条产出是否已含相同 key(去重).

    knowledge 类型按 detail.node_id 去重; 其它按 summary 去重。
    """
    key = None
    if ptype == "knowledge":
        key = (detail or {}).get("node_id")
    if key is None:
        key = f"{ptype}:{summary}"
    for p in reversed(list(productions)[-window:]):
        if p.get("type") == ptype and (
            (ptype == "knowledge" and (p.get("detail", {}) or {}).get("node_id") == key)
            or (ptype != "knowledge" and p.get("summary") == summary)
        ):
            return True
    return False


def summarize_issues(issues: Sequence[dict], since_minutes: int = 30) -> dict:
    """按时间窗过滤 issues 并统计 by_level."""
    cutoff = time.time() - since_minutes * 60
    recent = [i for i in issues if i.get("ts", 0) >= cutoff]
    by_level: dict[str, int] = {}
    for i in recent:
        lvl = i.get("level", "unknown")
        by_level[lvl] = by_level.get(lvl, 0) + 1
    return {
        "total": len(recent),
        "by_level": by_level,
        "since_minutes": since_minutes,
        "items": recent,
    }


__all__ = ["is_duplicate_production", "summarize_issues"]
