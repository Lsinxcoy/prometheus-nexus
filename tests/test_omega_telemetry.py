"""Tests for Omega.mechanism_telemetry() 接入点(架构优化 P2 接线).

验证意图:
1. mechanism_telemetry 在 mechanism_registry 存在时返回聚合快照
2. 机制经 wiring.run_phase 跑过后, 指标反映到 telemetry (last_error/calls)
3. mechanism_registry 缺失时降级返回空快照(不崩)

不实例化真 Omega(避免拉 5333 行 + uvicorn)。用 SimpleNamespace 模拟
最小 Omega 形态, 绑定类方法调用 — 仅验证接入点逻辑。
"""

from __future__ import annotations

from types import SimpleNamespace

from prometheus_nexus.mechanisms import MechanismRegistry, BaseMechanism, Phase
from prometheus_nexus.mechanisms.wiring import run_phase
from prometheus_nexus.life import Omega


class _M(BaseMechanism):
    name = "tm"
    category = "test"
    phase = Phase.REASON
    auto_wire = True

    def run(self, context: dict | None = None) -> dict:
        return {"ok": True}


def _fake_omega_with(reg: MechanismRegistry) -> SimpleNamespace:
    fake = SimpleNamespace(mechanism_registry=reg)
    # 绑定 Omega 的类方法到 fake 对象(不调 Omega.__init__)
    fake.mechanism_telemetry = Omega.mechanism_telemetry.__get__(fake)
    return fake


def test_telemetry_aggregates_registered_mechanisms():
    reg = MechanismRegistry()
    inst = _M()
    reg.register("tm", data={"executable": inst})
    # 跑一次产生指标
    run_phase(reg, Phase.REASON)
    omega = _fake_omega_with(reg)
    snap = omega.mechanism_telemetry()
    assert snap["total_mechanisms"] == 1
    assert snap["total_calls"] == 1
    assert snap["by_category"]["test"]["count"] == 1
    assert snap["mechanisms"][0]["name"] == "tm"


def test_telemetry_empty_on_missing_registry():
    # 无 mechanism_registry 属性 → 降级空快照
    fake = SimpleNamespace()
    fake.mechanism_telemetry = Omega.mechanism_telemetry.__get__(fake)
    snap = fake.mechanism_telemetry()
    assert snap["total_mechanisms"] == 0
    assert snap["mechanisms"] == []
