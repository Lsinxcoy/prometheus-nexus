"""Tests for 真拆 life.py 第五步: get_semantic_health → omega.monitor 委托.

验证意图(纯搬迁, 行为不变):
1. Omega.get_semantic_health() 委托到 monitor.get_semantic_health
2. 返回结构含 low_utility_ratio/sampled/kta_untranslated
3. store 为 None 时降级返回空结构(不崩)
"""

from __future__ import annotations

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega
from prometheus_nexus.omega.monitor import get_semantic_health


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_semantic_health_structure(omega: Omega):
    res = omega.get_semantic_health()
    assert isinstance(res, dict)
    assert "low_utility_ratio" in res
    assert "sampled" in res
    assert "kta_untranslated" in res
    assert 0.0 <= res["low_utility_ratio"] <= 1.0


def test_semantic_health_delegate_matches(omega: Omega):
    assert omega.get_semantic_health() == get_semantic_health(omega)


def test_semantic_health_handles_missing_store():
    class _Fake:
        store = None
    r = get_semantic_health(_Fake())
    assert r == {"low_utility_ratio": 0.0, "sampled": 0, "kta_untranslated": 0}
