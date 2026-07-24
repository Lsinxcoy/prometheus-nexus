"""Tests for MechanismRegistry.invoke 自动计时(主循环遥测接入点).

验证意图: 主循环经 registry.invoke() 调度的机制(硬编码调度也走它),
自动记录 latency/error 到机制 _metrics, 使 mechanism_telemetry() 真实产出。

不依赖 Omega / LLM。用真实 MechanismRegistry + BaseMechanism 实例。
"""

from __future__ import annotations

import time

from prometheus_nexus.mechanisms import MechanismRegistry, BaseMechanism, Phase
from prometheus_nexus.mechanisms.metrics import collect_registry_metrics
from prometheus_nexus.life import Omega
from prometheus_nexus.foundation.schema import ZConfig


class _TimedMech(BaseMechanism):
    name = "timed_mech"
    category = "test"
    phase = Phase.LEARN
    auto_wire = False

    def run(self, context: dict | None = None) -> dict:
        time.sleep(0.005)
        return {"ok": True}


class _ErrMech(BaseMechanism):
    name = "err_mech"
    category = "test"
    phase = Phase.LEARN
    auto_wire = False

    def run(self, context: dict | None = None) -> dict:
        raise RuntimeError("boom")


def test_invoke_records_latency():
    reg = MechanismRegistry()
    inst = _TimedMech()
    reg.register("timed_mech", data={"executable": inst})
    ok = reg.invoke("timed_mech", context={})
    assert ok is True
    # 经 invoke 自动计时
    assert inst._metrics["call_count"] == 1
    assert inst.avg_latency_ms > 0.0


def test_invoke_records_error():
    reg = MechanismRegistry()
    inst = _ErrMech()
    reg.register("err_mech", data={"executable": inst})
    ok = reg.invoke("err_mech")
    assert ok is False
    assert inst._metrics["error_count"] == 1
    assert inst._metrics["call_count"] == 1


def test_telemetry_produces_after_invoke():
    reg = MechanismRegistry()
    inst = _TimedMech()
    reg.register("timed_mech", data={"executable": inst})
    reg.invoke("timed_mech", context={})
    snap = collect_registry_metrics(reg)
    assert snap.total_calls == 1
    assert snap.total_latency_ms > 0.0
    assert snap.mechanisms[0]["metrics"]["avg_latency_ms"] > 0.0


def test_omega_telemetry_accumulates_on_invoke():
    o = Omega(ZConfig(database_path=":memory:"))
    try:
        # 注册一个机制并经由 registry.invoke 调用
        inst = _TimedMech()
        o.mechanism_registry.register("timed_mech", data={"executable": inst})
        o.mechanism_registry.invoke("timed_mech", context={})
        tel = o.mechanism_telemetry()
        # 该机制指标应被汇总
        m = next((x for x in tel["mechanisms"] if x["name"] == "timed_mech"), None)
        assert m is not None
        assert m["metrics"]["call_count"] == 1
    finally:
        o.close()
