"""store_stats — store 节点统计/映射辅助器官(架构优化: 从 life.py 外置).

外置动机
--------
life.py 尾部有一批"读 store.get_active_nodes → 映射/统计"的辅助方法
(_get_reasoning_chain / _collect_multi_agent_reasonings / _get_recent_trajectory /
_get_recent_actions / _compute_success_rate)。它们的核心逻辑是纯函数:
输入节点列表, 输出 dict/list/float。本不属于上帝调度流程, 是可外置并单测的器官。

按"保留上帝调度权、外置器官"原则:
- 本模块每个函数接收节点列表(或 store), 纯计算, 无 self 依赖。
- life.py 对应方法改为: 取 nodes → 调本模块函数, 行为逐行不变。
- 反馈/调度逻辑一律留在 life.py。

依赖
----
仅依赖节点对象的 .content / .utility / .id 属性; 测试中用 SimpleNamespace 构造假节点。
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

logger = logging.getLogger(__name__)


def collect_reasoning_chain(nodes: Sequence[Any], limit: int = 5) -> list[str]:
    """近期推理链(供 MCTS retriever). 取前 limit 个节点的 content[:100]."""
    return [n.content[:100] for n in list(nodes)[:limit]]


def collect_multi_agent_reasonings(nodes: Sequence[Any], limit: int = 5) -> list[dict]:
    """多 agent 推理采集(供 CARA 对齐检查)."""
    return [{"reasoning": n.content[:200], "confidence": n.utility} for n in list(nodes)[:limit]]


def collect_recent_trajectory(nodes: Sequence[Any]) -> list[dict]:
    """近期轨迹(供 COMPASS 审计)."""
    return [
        {"node_id": n.id, "content": n.content[:100], "utility": n.utility}
        for n in nodes
    ]


def collect_recent_actions(nodes: Sequence[Any]) -> list[dict]:
    """近期动作(供 StrategySwitcher). 以 remember 为 action, utility>0.5 为成功."""
    return [{"action": "remember", "success": n.utility > 0.5} for n in nodes]


def compute_success_rate(
    nodes: Sequence[Any],
    threshold: float = 0.6,
    default: float = 0.5,
) -> float:
    """成功率(供 StrategySwitcher). utility>threshold 视为成功.

    Args:
        nodes: 节点序列
        threshold: 成功阈值(默认 0.6)
        default: 空节点时返回(默认 0.5)

    Returns:
        float: 成功率 [0,1]
    """
    nodes = list(nodes)
    if not nodes:
        return default
    successful = sum(1 for n in nodes if n.utility > threshold)
    return successful / len(nodes)


__all__ = [
    "collect_reasoning_chain",
    "collect_multi_agent_reasonings",
    "collect_recent_trajectory",
    "collect_recent_actions",
    "compute_success_rate",
]
