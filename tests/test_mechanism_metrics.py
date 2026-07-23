"""Tests for 机制级遥测(架构优化 P2): BaseMechanism 指标 + wiring 自动计时 + 收集器.

验证意图:
1. BaseMechanism.meta() 含 metrics 块(latency/calls/errors), 初始为零
2. wiring.run_phase 自动计时: 跑完后 inst 的 avg_latency_ms > 0, call_count 递增
3. run_phase 异常时 record_error 被调用(error_count 递增)
4. collect_registry_metrics 聚合全量 + 按 category 汇总
5. export_prometheus_format 产出合法 prometheus 文本
"""

from __future__ import annotations

import time

from prometheus_nexus.mechanisms import (
    MechanismRegistry,
    BaseMechanism,
    Phase,
)
from prometheus_nexus.mechanisms.wiring import run_phase
from prometheus_nexus.mechanisms.metrics import (
    MetricsSnapshot,
    collect_registry_metrics,
    export_prometheus_format,
)


class _SlowMech(BaseMechanism):
    name = "slow_mech"
    category = "test"
    phase = Phase.REASON
    auto_wire = True

    def run(self, context: dict | None = None) -> dict:
        time.sleep(0.005)  # 制造可测延迟
        return {"ok": True}


class _ErrMech(BaseMechanism):
    name = "err_mech"
    category = "test"
    phase = Phase.LEARN
    auto_wire = True

    def run(self, context: dict | None = None) -> dict:
        raise RuntimeError("boom")


def test_meta_includes_metrics_zero_initially():
    m = _SlowMech()
    meta = m.meta()
    assert "metrics" in meta
    assert meta["metrics"]["call_count"] == 0
    assert meta["metrics"]["error_count"] == 0
    assert meta["metrics"]["avg_latency_ms"] == 0.0


def test_run_phase_auto_records_latency():
    reg = MechanismRegistry()
    inst = _SlowMech()
    reg.register("slow_mech", data={"executable": inst})
    run_phase(reg, Phase.REASON, context={})
    # 自动计时生效
    assert inst._metrics["call_count"] == 1
    assert inst.avg_latency_ms > 0.0
    # meta 反映
    assert inst.meta()["metrics"]["avg_latency_ms"] > 0.0


def test_run_phase_records_error():
    reg = MechanismRegistry()
    inst = _ErrMech()
    reg.register("err_mech", data={"executable": inst})
    results = run_phase(reg, Phase.LEARN)
    assert results[0]["ok"] is False
    assert inst._metrics["error_count"] == 1
    assert inst._metrics["last_error"] is not None
    # 异常路径仍记录延迟
    assert inst._metrics["call_count"] == 1


def test_collect_registry_metrics_aggregates():
    reg = MechanismRegistry()
    s = _SlowMech()
    e = _ErrMech()
    reg.register("slow_mech", data={"executable": s})
    reg.register("err_mech", data={"executable": e})
    # 先跑一次产生指标
    run_phase(reg, Phase.REASON)
    run_phase(reg, Phase.LEARN)

    snap = collect_registry_metrics(reg)
    assert isinstance(snap, MetricsSnapshot)
    assert snap.total_mechanisms == 2
    assert snap.auto_wired == 2
    assert snap.total_calls == 2
    assert snap.total_errors == 1
    assert snap.total_latency_ms > 0.0
    # 按 category 汇总
    assert snap.by_category["test"]["count"] == 2
    assert snap.by_category["test"]["errors"] == 1


def test_export_prometheus_format():
    reg = MechanismRegistry()
    s = _SlowMech()
    reg.register("slow_mech", data={"executable": s})
    run_phase(reg, Phase.REASON)
    snap = collect_registry_metrics(reg)
    text = export_prometheus_format(snap)
    assert "nexus_mechanism_calls_total" in text
    assert 'mechanism="slow_mech"' in text
    assert "nexus_mechanism_latency_ms_total" in text
