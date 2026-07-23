"""Tests for mechanisms.store_stats — 从 life.py 外置的节点统计器官.

验证意图(纯函数, 用 SimpleNamespace 假节点, 无需 Omega):
1. collect_reasoning_chain: 前 limit 个节点 content[:100]
2. collect_multi_agent_reasonings: {reasoning, confidence}
3. collect_recent_trajectory: {node_id, content, utility}
4. collect_recent_actions: {action:remember, success:utility>0.5}
5. compute_success_rate: utility>threshold 比例; 空→default
6. 外置验收: Omega 对应方法委托一致
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from prometheus_nexus.mechanisms.store_stats import (
    collect_reasoning_chain,
    collect_multi_agent_reasonings,
    collect_recent_trajectory,
    collect_recent_actions,
    compute_success_rate,
)
from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


def _n(id_: str, content: str, utility: float) -> SimpleNamespace:
    return SimpleNamespace(id=id_, content=content, utility=utility)


def test_reasoning_chain_limit():
    nodes = [_n(f"n{i}", f"content-{i}", 0.5) for i in range(8)]
    out = collect_reasoning_chain(nodes, limit=5)
    assert len(out) == 5
    assert out[0] == "content-0"[:100]


def test_multi_agent_reasonings_shape():
    nodes = [_n("a", "reason", 0.8), _n("b", "r2", 0.3)]
    out = collect_multi_agent_reasonings(nodes)
    assert out[0] == {"reasoning": "reason"[:200], "confidence": 0.8}


def test_recent_trajectory_shape():
    nodes = [_n("a", "c", 0.9)]
    out = collect_recent_trajectory(nodes)
    assert out[0] == {"node_id": "a", "content": "c"[:100], "utility": 0.9}


def test_recent_actions_success_flag():
    nodes = [_n("a", "c", 0.7), _n("b", "c", 0.4)]
    out = collect_recent_actions(nodes)
    assert out[0] == {"action": "remember", "success": True}
    assert out[1] == {"action": "remember", "success": False}


def test_success_rate_computation():
    nodes = [_n("a", "c", 0.8), _n("b", "c", 0.3), _n("c", "c", 0.9), _n("d", "c", 0.2)]
    # utility>0.6: a,c → 2/4 = 0.5
    assert compute_success_rate(nodes, threshold=0.6) == 0.5
    # 空 → default 0.5
    assert compute_success_rate([], default=0.5) == 0.5


# === 外置验收 ===


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_omega_store_stats_delegates(omega: Omega):
    # 空 store 时各方法应安全返回默认
    assert omega._get_reasoning_chain() == []
    assert omega._collect_multi_agent_reasonings() == []
    assert omega._get_recent_trajectory() == []
    assert omega._get_recent_actions() == []
    # 空节点成功率默认 0.5
    assert omega._compute_success_rate() == 0.5
