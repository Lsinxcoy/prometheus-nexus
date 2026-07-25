"""Tests for 真拆 life.py 收尾: dopamine gate 决策 → omega.gates 委托.

验证意图(外置决策判断, 副作用留上帝):
1. should_reject_dopamine 在 bypass_dopamine=True 时返回 False(不拒)
2. 低 utility 且 bypass_dopamine=False 时 gate 决策为 reject(返回 True)
3. Omega.remember 低 utility 行为不变(被拒返回 "")
4. Omega.remember 高 utility 行为不变(写入)
"""

from __future__ import annotations

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega
from prometheus_nexus.omega.gates import should_reject_dopamine


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_bypass_skips_reject(omega: Omega):
    assert should_reject_dopamine(omega, utility=0.01, surprise=0.0,
                                   bypass_dopamine=True) is False


def test_low_utility_rejected_when_not_bypassed(omega: Omega):
    # 低 utility 应触发 dopamine reject(决策为 True)
    assert should_reject_dopamine(omega, utility=0.01, surprise=0.0,
                                   bypass_dopamine=False) is True


def test_remember_low_utility_rejected(omega: Omega):
    before = omega.store.get_node_count()
    nid = omega.remember("seed low-utility fact that dopamine should reject",
                         utility=0.01, bypass_dopamine=False)
    assert nid == ""
    assert omega.store.get_node_count() == before


def test_remember_high_utility_stored(omega: Omega):
    before = omega.store.get_node_count()
    nid = omega.remember("Quarterly report shows 18% revenue growth in Q3 2026.",
                         utility=0.95, bypass_dopamine=False)
    assert nid
    assert omega.store.get_node_count() == before + 1
