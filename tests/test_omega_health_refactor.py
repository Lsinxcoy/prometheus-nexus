"""Tests for 真拆 life.py 第三步: 健康采集/聚合 → omega.health 委托.

验证意图(纯搬迁, 行为不变):
1. Omega.status() 仍返回健康态(_compute_health 委托生效)
2. collect_component_health(self) 可独立调用(返回 details + failed)
3. compute_health(self) 可独立调用(空库返回 empty)
"""

from __future__ import annotations

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega
from prometheus_nexus.omega.health import collect_component_health, compute_health


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_status_health_via_delegate(omega: Omega):
    # status() 经 _compute_health 委托 → 返回健康等级
    st = omega.status()
    assert st.health in ("empty", "healthy", "degraded", "critical", "unknown")


def test_collect_component_health_callable(omega: Omega):
    details, failed = collect_component_health(omega)
    assert isinstance(details, dict)
    assert isinstance(failed, list)
    # 探针表非空(至少有 bank 等组件被探测)
    assert len(details) > 0


def test_compute_health_empty_for_blank(omega: Omega):
    # :memory: 空库 → empty
    assert compute_health(omega) == "empty"


def test_omega_methods_are_delegates(omega: Omega):
    assert omega._collect_component_health() == collect_component_health(omega)
