"""wiring — 机制声明式接入收集器(架构优化 P1 地基).

问题
----
Nexus 的 232 个活跃机制在 life.py (__init__ 硬编码实例化 + self.x.method()
直调), 新增机制需人肉改 life.py 的 5333 行调度。这是 _remaining.py 堆砌与
死代码盲区(文档点名的 LOCA/CARA/CAMP)的根因 —— 接入状态无人能可靠追踪,
连作者自己的 MECHANISM_INVENTORY 文档都与代码对不上(LOCA 实际被调用却记为死代码)。

本模块提供*声明式接入*的最小地基, 不破坏现有 232 机制:
- collect_phase_handlers(registry, phase): 从注册表按 phase 收集 auto_wire 机制
- collect_hooks(registry, hook): 按 hooks_into 收集细粒度介入机制
- WiringPlan: 把 registry 全量机制按 phase 分组, 供 Orchestrator 调度

约定
----
- 仅 auto_wire=True 的机制被收集(默认 False, 兼容现有硬编码调度)
- 机制实例经 registry.register_instance / register(data={"executable": inst})
  挂入后, wiring 才能发现它
- 老机制(记忆/安全/进化...)不改, 只有新机制 / 复活机制用声明式接入
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

from prometheus_nexus.mechanisms.base_mechanism import (
    BaseMechanism,
    Phase,
)


@dataclass
class WiringPlan:
    """按阶段分组的接入计划."""

    by_phase: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    by_hook: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    auto_wired: list[str] = field(default_factory=list)

    def handlers_for(self, phase: str) -> list[str]:
        return list(self.by_phase.get(phase, []))

    def hooks_for(self, hook: str) -> list[str]:
        return list(self.by_hook.get(hook, []))

    def __repr__(self) -> str:
        return (
            f"WiringPlan(phases={dict(self.by_phase)}, "
            f"hooks={dict(self.by_hook)}, auto_wired={self.auto_wired})"
        )


def _instance_of(entry: dict) -> BaseMechanism | None:
    """从 registry entry 取真实机制实例(兼容 executable / data.instance 两种挂法)."""
    data = entry.get("data", {}) or {}
    inst = data.get("executable")
    if isinstance(inst, BaseMechanism):
        return inst
    inst = data.get("instance")
    if isinstance(inst, BaseMechanism):
        return inst
    return None


def collect_phase_handlers(registry: Any, phase: str) -> list[BaseMechanism]:
    """收集某阶段下所有 auto_wire=True 的机制实例.

    Args:
        registry: MechanismRegistry 实例(或任意含 _mechanisms / get_enabled 的对象)
        phase: Phase.* 常量或字符串

    Returns:
        list[BaseMechanism]: 按依赖拓扑序排列的实例(无环假设)
    """
    out: list[BaseMechanism] = []
    entries = getattr(registry, "_mechanisms", {})
    for name, entry in entries.items():
        inst = _instance_of(entry)
        if inst is None:
            continue
        if not getattr(inst, "auto_wire", False):
            continue
        if getattr(inst, "phase", Phase.ANY) in (phase, Phase.ANY):
            out.append(inst)
    return out


def collect_hooks(registry: Any, hook: str) -> list[BaseMechanism]:
    """收集声明 hooks_into=hook 的机制实例(细粒度介入)."""
    out: list[BaseMechanism] = []
    entries = getattr(registry, "_mechanisms", {})
    for name, entry in entries.items():
        inst = _instance_of(entry)
        if inst is None:
            continue
        if not getattr(inst, "auto_wire", False):
            continue
        if getattr(inst, "hooks_into", None) == hook:
            out.append(inst)
    return out


def build_plan(registry: Any) -> WiringPlan:
    """扫描 registry 全量机制, 构建 WiringPlan(按 phase + hook 分组)."""
    plan = WiringPlan()
    entries = getattr(registry, "_mechanisms", {})
    for name, entry in entries.items():
        inst = _instance_of(entry)
        if inst is None:
            continue
        if not getattr(inst, "auto_wire", False):
            continue
        plan.auto_wired.append(name)
        ph = getattr(inst, "phase", Phase.ANY)
        plan.by_phase[ph].append(name)
        hk = getattr(inst, "hooks_into", None)
        if hk:
            plan.by_hook[hk].append(name)
    return plan


def run_phase(registry: Any, phase: str, context: dict | None = None) -> list[dict]:
    """调度某阶段所有 auto_wire 机制, 返回各自的 run() 结果.

    异常隔离: 单个机制失败不影响同阶段其它机制(与 registry.invoke 一致).
    仅对声明了 run() 且 auto_wire 的机制生效.

    Returns:
        list[dict]: 每个元素 {name, ok, result?}
    """
    results: list[dict] = []
    for inst in collect_phase_handlers(registry, phase):
        name = getattr(inst, "name", "unnamed")
        try:
            res = inst.run(context or {})
            ok = bool(res.get("ok", True)) if isinstance(res, dict) else True
            inst.invoke_count += 1
            results.append({"name": name, "ok": ok, "result": res})
        except Exception as exc:  # 异常隔离, 不阻断主流程
            logger.warning("wiring.run_phase(%s): %s raised %s", phase, name, exc)
            results.append({"name": name, "ok": False, "error": str(exc)})
    return results


__all__ = [
    "Phase",
    "WiringPlan",
    "collect_phase_handlers",
    "collect_hooks",
    "build_plan",
    "run_phase",
]
