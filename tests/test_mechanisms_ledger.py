"""Tests for mechanisms.ledger — 从 life.py 外置的账本纯逻辑器官.

验证意图(纯函数, 用 dict/list 假数据, 无需 Omega):
1. is_duplicate_production: knowledge 按 node_id 去重; 其它按 summary; window 生效
2. summarize_issues: 时间窗过滤 + by_level 计数
3. 外置验收: Omega.record_production 去重 / _get_issues 委托一致
"""

from __future__ import annotations

import time

import pytest

from prometheus_nexus.mechanisms.ledger import is_duplicate_production, summarize_issues
from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


# === is_duplicate_production ===


def test_dup_knowledge_by_node_id():
    prods = [{"type": "knowledge", "summary": "s", "detail": {"node_id": "n1"}}]
    assert is_duplicate_production(prods, "knowledge", "other", {"node_id": "n1"}) is True
    assert is_duplicate_production(prods, "knowledge", "other", {"node_id": "n2"}) is False


def test_dup_non_knowledge_by_summary():
    prods = [{"type": "mechanism", "summary": "made X"}]
    assert is_duplicate_production(prods, "mechanism", "made X") is True
    assert is_duplicate_production(prods, "mechanism", "made Y") is False


def test_dup_window_limits_scope():
    # 第 201 条前的相同 summary 应超出 window=200 不被判重
    prods = [{"type": "reflection", "summary": f"s{i}"} for i in range(200)]
    prods.append({"type": "reflection", "summary": "old"})
    # 末尾追加 200 条新 summary, 使 "old" 超出 window
    prods += [{"type": "reflection", "summary": f"new{i}"} for i in range(200)]
    assert is_duplicate_production(prods, "reflection", "old", window=200) is False


# === summarize_issues ===


def test_summarize_filters_by_window_and_counts():
    now = time.time()
    issues = [
        {"ts": now, "level": "error", "source": "x", "msg": "a"},
        {"ts": now, "level": "error", "source": "y", "msg": "b"},
        {"ts": now - 3600, "level": "warning", "source": "z", "msg": "c"},  # 1h 前
    ]
    res = summarize_issues(issues, since_minutes=30)
    assert res["total"] == 2
    assert res["by_level"] == {"error": 2}
    assert res["since_minutes"] == 30


# === 外置验收 ===


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_omega_record_production_dedup(omega: Omega):
    omega.record_production("mechanism", "unique-mech-A")
    # 再次记相同 summary → 应被去重(不新增)
    before = len(omega._productions)
    omega.record_production("mechanism", "unique-mech-A")
    assert len(omega._productions) == before


def test_omega_get_issues_delegates(omega: Omega):
    res = omega._get_issues(since_minutes=30)
    assert "total" in res and "by_level" in res and "items" in res
