"""Tests for 真拆 life.py 第四步: get_mechanism_consumption → omega.monitor 委托.

验证意图(纯搬迁, 行为不变):
1. Omega.get_mechanism_consumption() 委托到 monitor.get_mechanism_consumption
2. 返回结构含 total/consumed/rate/silent_by_category 等
3. nexus 为 None 时降级返回空结构(不崩)
"""

from __future__ import annotations

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega
from prometheus_nexus.omega.monitor import get_mechanism_consumption


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_consumption_structure(omega: Omega):
    res = omega.get_mechanism_consumption()
    assert isinstance(res, dict)
    assert "total" in res
    assert "consumed" in res
    assert "rate" in res
    assert "silent_by_category" in res
    # 分类桶齐全
    for k in ("test_residue", "orphan_registry", "dormant_ok", "trigger_missing"):
        assert k in res["silent_by_category"]


def test_consumption_delegate_matches(omega: Omega):
    assert omega.get_mechanism_consumption() == get_mechanism_consumption(omega)


def test_consumption_handles_missing_nexus():
    # 构造无 nexus 的假对象
    class _Fake:
        nexus = None
    r = get_mechanism_consumption(_Fake())
    assert r == {"total": 0, "consumed": 0, "rate": 0.0, "by_carrier": {}}
