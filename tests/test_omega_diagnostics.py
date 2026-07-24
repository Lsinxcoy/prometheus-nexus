"""Tests for Omega.diagnostics — 遥测生产化合一诊断出口.

验证意图:
1. diagnostics() 返回 {system, mechanisms, mechanism_summary}
2. system 含 SystemStatus 字段(node_count/health 等)
3. mechanism_summary 含 total_calls/total_errors/by_category/top_by_calls
4. 经 registry.invoke 累积调用后, summary.total_calls > 0(遥测真实产出)
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
        time.sleep(0.003)
        return {"ok": True}


@pytest.fixture(scope="session")
def omega() -> Omega:
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_diagnostics_shape(omega: Omega):
    d = omega.diagnostics()
    assert set(d.keys()) >= {"system", "mechanisms", "mechanism_summary"}
    assert "node_count" in d["system"]
    assert "health" in d["system"]


def test_diagnostics_summary_present(omega: Omega):
    d = omega.diagnostics()
    s = d["mechanism_summary"]
    assert "total_calls" in s
    assert "total_errors" in s
    assert "by_category" in s
    assert "top_by_calls" in s
    assert isinstance(s["top_by_calls"], list)


def test_diagnostics_reflects_invoke(omega: Omega):
    inst = _TimedMech()
    omega.mechanism_registry.register("timed_mech", data={"executable": inst})
    omega.mechanism_registry.invoke("timed_mech", context={})
    d = omega.diagnostics()
    assert d["mechanism_summary"]["total_calls"] >= 1
    top = d["mechanism_summary"]["top_by_calls"]
    assert any(t["name"] == "timed_mech" and t["call_count"] >= 1 for t in top)
