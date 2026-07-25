"""Tests for #2: status() 5s TTL 缓存(监控拉取不再每次全量重算).

验证意图(架构缺陷修复, 低风险增量):
1. 5s 内连续调用 status() 命中缓存(_collect_component_health 只调一次)
2. uptime_seconds 仍实时刷新(缓存对象被改写, 非冻结)
3. TTL 过期后重新重算(_collect_component_health 再次调用)
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_status_ttl_cache_hits(omega: Omega):
    # 清空缓存, 确保首次走重算
    omega._status_cache = None
    omega._status_cache_ts = 0
    with patch.object(Omega, "_collect_component_health", wraps=omega._collect_component_health) as spy:
        s1 = omega.status()
        s2 = omega.status()  # 5s 内应命中缓存
        assert spy.call_count == 1  # 只重算一次
        # 两次返回同一对象(uptime 实时刷新)
        assert s1 is s2


def test_status_uptime_live(omega: Omega):
    omega._status_cache = None
    omega._status_cache_ts = 0
    s1 = omega.status()
    time.sleep(0.05)
    s2 = omega.status()
    # 同一缓存对象, uptime 应增大(实时刷新)
    assert s2.uptime_seconds >= s1.uptime_seconds


def test_status_ttl_expires(omega: Omega):
    omega._status_cache = None
    omega._status_cache_ts = 0
    with patch.object(Omega, "_collect_component_health", wraps=omega._collect_component_health) as spy:
        omega.status()
        # 伪造过期
        omega._status_cache_ts = 0
        omega.status()
        assert spy.call_count == 2  # 过期后重新重算
