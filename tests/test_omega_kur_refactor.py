"""Tests for 真拆 life.py 第八步: knowledge_utilization_report → omega.monitor 委托.

验证意图(纯搬迁, 行为不变):
1. Omega.knowledge_utilization_report() 委托到 monitor.knowledge_utilization_report
2. 返回结构含 total_nodes/recall_hit_rate/focus_topics 等
3. 异常降级返回 {error: ...}
"""

from __future__ import annotations

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega
from prometheus_nexus.omega.monitor import knowledge_utilization_report


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_kur_structure(omega: Omega):
    res = omega.knowledge_utilization_report()
    assert isinstance(res, dict)
    assert "total_nodes" in res
    assert "recall_total_hits" in res
    assert "recall_hit_rate" in res
    assert "focus_topics" in res


def test_kur_delegate_matches(omega: Omega):
    assert omega.knowledge_utilization_report() == knowledge_utilization_report(omega)


def test_kur_handles_missing_store():
    class _Fake:
        store = None
    # store 为 None → get_node_count 抛 → 异常降级
    r = knowledge_utilization_report(_Fake())
    assert "error" in r
