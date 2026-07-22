"""Tests for 架构优化 P1: 机制声明式接入地基(wiring + BaseMechanism 扩展).

验证意图(非行为):
1. BaseMechanism 新增 phase / hooks_into / auto_wire 声明字段, 默认兼容(不破老机制)
2. 老机制(auto_wire=False)不被 wiring 收集 —— 兼容现有 232 硬编码调度
3. auto_wire=True 的机制能被 collect_phase_handlers 按 phase 收集
4. collect_hooks 按 hooks_into 收集细粒度介入
5. build_plan 能分组, run_phase 真正调度并隔离异常
6. registry 旧 API(register/enable/invoke)仍工作, 接入可执行实例后 invoke 派发
"""

from __future__ import annotations

import pytest

from prometheus_nexus.mechanisms import (
    MechanismRegistry,
    BaseMechanism,
    Phase,
)
from prometheus_nexus.mechanisms.wiring import (
    WiringPlan,
    collect_phase_handlers,
    collect_hooks,
    build_plan,
    run_phase,
)


# ===================================================================
# 假机制(声明式接入)
# ===================================================================


class _EvolveMech(BaseMechanism):
    name = "fake_evolve"
    phase = Phase.EVOLVE
    auto_wire = True

    def __init__(self) -> None:
        super().__init__()
        self.ran = False
        self.last_ctx: dict | None = None

    def run(self, context: dict | None = None) -> dict:
        self.ran = True
        self.last_ctx = context
        return {"ok": True, "name": self.name}


class _HookMech(BaseMechanism):
    name = "fake_hook"
    phase = Phase.ANY
    hooks_into = "after_store"
    auto_wire = True

    def run(self, context: dict | None = None) -> dict:
        return {"ok": True}


class _BoomMech(BaseMechanism):
    name = "fake_boom"
    phase = Phase.LEARN
    auto_wire = True

    def run(self, context: dict | None = None) -> dict:
        raise RuntimeError("boom in run")


class _LegacyMech(BaseMechanism):
    """auto_wire 默认 False, 模拟既有 232 硬编码机制."""

    name = "legacy_mech"

    def run(self, context: dict | None = None) -> dict:
        return {"ok": True}


# ===================================================================
# 兼容性: 默认字段不破老机制
# ===================================================================


def test_base_mechanism_defaults_compatible():
    m = _LegacyMech()
    assert m.auto_wire is False
    assert m.phase == Phase.ANY
    assert m.hooks_into is None
    meta = m.meta()
    assert "phase" in meta and "auto_wire" in meta and "hooks_into" in meta


def test_legacy_not_collected_by_wiring():
    reg = MechanismRegistry()
    reg.register("legacy_mech", data={"executable": _LegacyMech()})
    # auto_wire=False → 不被收集
    assert collect_phase_handlers(reg, Phase.EVOLVE) == []
    assert build_plan(reg).auto_wired == []


# ===================================================================
# 声明式接入: 收集与调度
# ===================================================================


def test_collect_phase_handlers():
    reg = MechanismRegistry()
    ev = _EvolveMech()
    reg.register("fake_evolve", data={"executable": ev})
    handlers = collect_phase_handlers(reg, Phase.EVOLVE)
    assert len(handlers) == 1
    assert handlers[0] is ev


def test_collect_hooks():
    reg = MechanismRegistry()
    hk = _HookMech()
    reg.register("fake_hook", data={"executable": hk})
    hooks = collect_hooks(reg, "after_store")
    assert len(hooks) == 1
    assert hooks[0] is hk


def test_build_plan_groups():
    reg = MechanismRegistry()
    reg.register("fake_evolve", data={"executable": _EvolveMech()})
    reg.register("fake_hook", data={"executable": _HookMech()})
    plan = build_plan(reg)
    assert set(plan.auto_wired) == {"fake_evolve", "fake_hook"}
    assert plan.handlers_for(Phase.EVOLVE) == ["fake_evolve"]
    assert plan.hooks_for("after_store") == ["fake_hook"]


def test_run_phase_dispatches():
    reg = MechanismRegistry()
    ev = _EvolveMech()
    reg.register("fake_evolve", data={"executable": ev})
    results = run_phase(reg, Phase.EVOLVE, context={"x": 1})
    assert len(results) == 1
    assert results[0]["ok"] is True
    assert ev.ran is True
    assert ev.last_ctx == {"x": 1}
    assert ev.invoke_count == 1


def test_run_phase_isolates_exceptions():
    reg = MechanismRegistry()
    reg.register("fake_evolve", data={"executable": _EvolveMech()})
    reg.register("fake_boom", data={"executable": _BoomMech()})
    results = run_phase(reg, Phase.LEARN)
    # 两个都该出现在结果里, boom 的 ok=False 但不影响 evolve 那个
    by_name = {r["name"]: r for r in results}
    assert by_name["fake_boom"]["ok"] is False
    assert "error" in by_name["fake_boom"]


# ===================================================================
# registry 旧 API 仍工作(向后兼容)
# ===================================================================


def test_registry_legacy_invoke_counts():
    reg = MechanismRegistry()
    r = reg.register("a", data={}, dependencies=[])
    assert r["registered"] is True
    assert reg.invoke("a") is True
    assert reg.get_enabled() == ["a"]


def test_registry_invoke_dispatches_executable():
    reg = MechanismRegistry()
    ev = _EvolveMech()
    reg.register("fake_evolve", data={"executable": ev})
    reg.enable("fake_evolve")
    assert reg.invoke("fake_evolve") is True
    assert ev.ran is True
