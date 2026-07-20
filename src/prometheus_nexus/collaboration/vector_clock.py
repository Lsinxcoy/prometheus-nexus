"""向量时钟 — 因果排序与偏序关系检测

基于 vector clocks 经典论文 (Mattern 1989) 实现：
- 向量时钟的自增、合并、比较操作
- 因果关系的判定（happens-before、concurrent）
- Lamport 时间戳辅助排序
- 全局快照（Chandy-Lamport 算法简化版）

使用函数式风格，所有状态通过参数传入/返回。
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
import hashlib
from typing import Dict, List, Optional, Tuple, Any


# ==================== 向量时钟核心操作 ====================

def new_vector_clock(node_id: str) -> dict:
    """创建一个新节点的空向量时钟"""
    return {"node_id": node_id, "clock": {node_id: 0}}


def increment(clock: dict) -> dict:
    """本地事件发生时，自增本节点分量"""
    clock = dict(clock)
    clock["clock"] = dict(clock["clock"])
    node = clock["node_id"]
    clock["clock"][node] = clock["clock"].get(node, 0) + 1
    return clock


def merge(clock: dict, incoming_clock: dict[str, int]) -> dict:
    """接收消息时合并外部时钟：分��取最大值"""
    clock = dict(clock)
    clock["clock"] = dict(clock["clock"])
    for node, ts in incoming_clock.items():
        clock["clock"][node] = max(clock["clock"].get(node, 0), ts)
    # 合并后自增本节点分量
    node = clock["node_id"]
    clock["clock"][node] = clock["clock"].get(node, 0) + 1
    return clock


def get_clock(clock: dict) -> dict[str, int]:
    """获取时钟分量的深拷贝"""
    return dict(clock["clock"])


# ==================== 因果关系判定 ====================

def happens_before(vc1: dict[str, int], vc2: dict[str, int]) -> bool:
    """
    判定 vc1 是否在 vc2 之前发生（vc1 → vc2）
    条件：所有分量 vc1[i] <= vc2[i] 且存在至少一个严格小于
    """
    all_nodes = set(vc1.keys()) | set(vc2.keys())
    if not all_nodes:
        return False

    all_le = True
    any_lt = False
    for node in all_nodes:
        v1 = vc1.get(node, 0)
        v2 = vc2.get(node, 0)
        if v1 > v2:
            all_le = False
            break
        if v1 < v2:
            any_lt = True

    return all_le and any_lt


def concurrent(vc1: dict[str, int], vc2: dict[str, int]) -> bool:
    """
    判定两个事件是否并发：互不因果
    条件：存在分量 vc1[i] > vc2[i] 且存在分量 vc1[j] < vc2[j]
    """
    all_nodes = set(vc1.keys()) | set(vc2.keys())
    if not all_nodes:
        return True

    has_greater = False
    has_less = False
    for node in all_nodes:
        v1 = vc1.get(node, 0)
        v2 = vc2.get(node, 0)
        if v1 > v2:
            has_greater = True
        elif v1 < v2:
            has_less = True
        if has_greater and has_less:
            return True

    return False


def equal_clocks(vc1: dict[str, int], vc2: dict[str, int]) -> bool:
    """判定两个向量时钟是否完全相等"""
    all_nodes = set(vc1.keys()) | set(vc2.keys())
    for node in all_nodes:
        if vc1.get(node, 0) != vc2.get(node, 0):
            return False
    return True


def compare_clocks(vc1: dict[str, int], vc2: dict[str, int]) -> str:
    """
    综合比较两个向量时钟，返回关系描述
    返回值：'before', 'after', 'concurrent', 'equal'
    """
    if equal_clocks(vc1, vc2):
        return "equal"
    if happens_before(vc1, vc2):
        return "before"
    if happens_before(vc2, vc1):
        return "after"
    return "concurrent"


# ==================== Lamport 时间戳 ====================

def compute_lamport_timestamp(vc: dict[str, int]) -> int:
    """
    从向量时钟导出 Lamport 时间戳：所有分量之和
    用于全局逻辑排序（牺牲因果关系保留总序）
    """
    return sum(vc.values())


def lamport_sort(events: List[dict]) -> List[dict]:
    """
    使用 Lamport 时间戳对事件列表进行排序
    events: [{"clock": {...}, "payload": ...}, ...]
    """
    decorated = []
    for evt in events:
        lamport_ts = compute_lamport_timestamp(evt["clock"])
        decorated.append((lamport_ts, evt))
    decorated.sort(key=lambda x: x[0])
    return [evt for _, evt in decorated]


# ==================== 因果排序 ====================

def topological_sort_events(events: List[dict]) -> List[dict]:
    """
    基于向量时钟的偏序拓扑排序
    使用 Kahn 算法，无法排序的并发事件按 Lamport 时间戳排序
    """
    if not events:
        return []

    n = len(events)
    # ���算入度矩阵
    in_degree = [0] * n
    adj: List[List[int]] = [[] for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i != j and happens_before(events[i]["clock"], events[j]["clock"]):
                adj[i].append(j)
                in_degree[j] += 1

    # Kahn 算法
    queue = [i for i in range(n) if in_degree[i] == 0]
    result: List[dict] = []

    while queue:
        # 从入度为 0 的节点中选择 Lamport 时间戳最小的
        queue.sort(key=lambda i: compute_lamport_timestamp(events[i]["clock"]))
        node = queue.pop(0)
        result.append(events[node])
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # 剩余并发事件按 Lamport 时间戳排序后追加
    remaining = [events[i] for i in range(n) if in_degree[i] > 0]
    remaining.sort(key=lambda e: compute_lamport_timestamp(e["clock"]))
    result.extend(remaining)

    return result


# ==================== 时钟压缩 ====================

def compress_clock(vc: dict[str, int], max_entries: int = 50) -> dict[str, int]:
    """
    向量时钟压缩：只保留非零分量中值最大的 max_entries 个节点
    用于分布式系统中节点数量众多时的存储优化
    """
    if len(vc) <= max_entries:
        return dict(vc)

    # 过滤零值
    non_zero = {k: v for k, v in vc.items() if v > 0}
    if len(non_zero) <= max_entries:
        return non_zero

    # 保留值最大的 top-K 节点
    sorted_nodes = sorted(non_zero.items(), key=lambda x: x[1], reverse=True)
    return dict(sorted_nodes[:max_entries])


# ==================== 全局快照 ====================

def chandy_lamport_snapshot(
    node_clocks: Dict[str, dict[str, int]],
    channels: List[Tuple[str, str, List[dict]]],
    initiator: str,
) -> dict:
    """
    简化的 Chandy-Lamport 全局快照
    node_clocks: 各节点当前向量时钟
    channels: [(sender, receiver, pending_messages), ...]
    返回全局一致快照
    """
    snapshot: Dict[str, Any] = {"node_states": {}, "channel_states": {}}

    # 记录发起者快照
    snapshot["node_states"][initiator] = dict(node_clocks.get(initiator, {}))

    # 记录发起者的出边通道状态（已清空）
    for sender, receiver, msgs in channels:
        if sender == initiator:
            snapshot["channel_states"][f"{sender}->{receiver}"] = []
        else:
            snapshot["channel_states"][f"{sender}->{receiver}"] = list(msgs)

    # 记录其他节点状态
    for node, clock in node_clocks.items():
        if node != initiator:
            snapshot["node_states"][node] = dict(clock)

    snapshot["initiator"] = initiator
    snapshot["timestamp"] = time.time()
    snapshot["node_count"] = len(node_clocks)

    return snapshot


# ==================== 统计与诊断 ====================

def clock_statistics(vc: dict[str, int]) -> dict:
    """计算向量时钟的统计信息"""
    if not vc:
        return {"nodes": 0, "total_ticks": 0, "max": 0, "min": 0, "mean": 0}

    values = list(vc.values())
    return {
        "nodes": len(vc),
        "total_ticks": sum(values),
        "max": max(values),
        "min": min(values),
        "mean": sum(values) / len(values),
    }


def compute_causal_chain_length(events: List[dict]) -> int:
    """
    计算事件列表中最长因果链的长度
    用于评估系统因果关系的复杂度
    """
    n = len(events)
    if n == 0:
        return 0

    # 计算每个事件的最长因果链
    chain_len = [1] * n

    sorted_events = sorted(range(n), key=lambda i: compute_lamport_timestamp(events[i]["clock"]))

    for idx in sorted_events:
        for j in range(n):
            if j != idx and happens_before(events[j]["clock"], events[idx]["clock"]):
                chain_len[idx] = max(chain_len[idx], chain_len[j] + 1)

    return max(chain_len)


def detect_orphan_events(events: List[dict]) -> List[int]:
    """
    检测孤立事件：不与任何其他事件存在因果关系
    """
    orphans = []
    n = len(events)
    for i in range(n):
        is_connected = False
        for j in range(n):
            if i != j:
                if happens_before(events[i]["clock"], events[j]["clock"]) or \
                   happens_before(events[j]["clock"], events[i]["clock"]):
                    is_connected = True
                    break
        if not is_connected:
            orphans.append(i)
    return orphans


def merge_multiple_clocks(clocks: List[dict[str, int]]) -> dict[str, int]:
    """合并多个向量时钟，每个分量取最大值"""
    merged: dict[str, int] = {}
    for vc in clocks:
        for node, ts in vc.items():
            merged[node] = max(merged.get(node, 0), ts)
    return merged


# 兼容性：为 life.py 提供一个 VectorClock 包装类
class VectorClock:
    def __init__(self, node_id: str = "omega"):
        self.clock = new_vector_clock(node_id)
    def increment(self):
        self.clock = increment(self.clock)
        return self.clock
    def merge(self, incoming_clock: dict):
        self.clock = merge(self.clock, incoming_clock)
        return self.clock
    def get_clock(self):
        return dict(self.clock)
    def happens_before(self, other_clock: dict):
        return happens_before(self.clock, other_clock)
    def are_concurrent(self, other_clock: dict):
        return are_concurrent(self.clock, other_clock)
