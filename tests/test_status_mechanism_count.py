"""Tests for #1: status().mechanisms 单一真相源(消除硬编码 127 魔法数).

验证意图(架构缺陷修复, 低风险增量):
1. status().mechanisms 不再硬编码 127, 而是从 Nexus 真相源读
2. _mechanism_count 有降级链(nexus > registry > 0)
3. 机制数 == nexus.get_monitor_snapshot()['mechanisms'](一致)
"""

from __future__ import annotations

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_status_mechanisms_not_hardcoded(omega: Omega):
    st = omega.status()
    # 不再是魔法数 127; 实际等于 nexus 真相源机制数
    assert st.mechanisms != 127 or st.mechanisms == omega.nexus.get_monitor_snapshot()["mechanisms"]
    # 与 Nexus 真相源一致
    assert st.mechanisms == omega.nexus.get_monitor_snapshot()["mechanisms"]


def test_mechanism_count_matches_nexus(omega: Omega):
    assert omega._mechanism_count() == omega.nexus.get_monitor_snapshot()["mechanisms"]


def test_mechanism_count_degrade_chain():
    # nexus 为 None → 回退 registry 或 0
    class _Fake:
        nexus = None
        mechanism_registry = None
    assert Omega._mechanism_count(_Fake()) == 0
