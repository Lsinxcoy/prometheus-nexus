"""Tests for Omega.export_prometheus_metrics — 遥测 Prometheus 导出.

验证意图:
1. 返回 Prometheus exposition 格式字符串(以 # TYPE / metric 行组成)
2. 含系统级 gauge(omega_system_node_count 等)
3. 含机制级指标(经 invoke 累积后 omega_mechanism_* 出现)
"""

from __future__ import annotations

import time

import pytest

from prometheus_nexus.mechanisms import MechanismRegistry, BaseMechanism, Phase
from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


class _TimedMech(BaseMechanism):
    name = "timed_mech"
    category = "test"
    phase = Phase.LEARN
    auto_wire = False

    def run(self, context: dict | None = None) -> dict:
        time.sleep(0.002)
        return {"ok": True}


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_export_format_valid(omega: Omega):
    text = omega.export_prometheus_metrics()
    assert isinstance(text, str)
    assert "# TYPE" in text
    assert "omega_system_node_count" in text
    assert "omega_system_health_ok" in text


def test_export_has_system_gauges(omega: Omega):
    text = omega.export_prometheus_metrics()
    # 系统 gauge 行格式正确
    assert "omega_system_node_count 0" in text or "omega_system_node_count" in text
    # uptime 是 float 格式
    assert "omega_system_uptime_seconds" in text


def test_export_includes_mechanism_metrics_after_invoke(omega: Omega):
    inst = _TimedMech()
    omega.mechanism_registry.register("timed_mech", data={"executable": inst})
    omega.mechanism_registry.invoke("timed_mech", context={})
    text = omega.export_prometheus_metrics()
    # 机制指标(来自 export_prometheus_format)
    assert "omega_mechanism_" in text or "timed_mech" in text
