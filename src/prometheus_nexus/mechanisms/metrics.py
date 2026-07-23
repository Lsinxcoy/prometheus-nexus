"""metrics — 机制级遥测收集器(架构优化 P2 地基).

问题背景
--------
Nexus 的 monitor/ 仅离线静态审计脚本; TelemetryPipeline 只测系统级(管道)信号,
不接入机制级。你叫 Prometheus 却无运行时机制指标 — 不知道哪个机制在烧 token /
哪个在拖延迟 / 哪个失败率高。

本模块提供零外部依赖的轻量收集器(不引 prometheus-client/opentelemetry, 避免
环境依赖风险): 遍历 registry 所有机制, 汇总 meta() + 运行时指标, 输出快照 dict,
供宿主 / 监控 / TelemetryPipeline 拉取或导出。

与 P1 关系: BaseMechanism._metrics 由 wiring.run_phase 自动填充, 本收集器读取它。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism


@dataclass
class MetricsSnapshot:
    """全量机制指标快照."""

    total_mechanisms: int = 0
    auto_wired: int = 0
    total_calls: int = 0
    total_errors: int = 0
    total_latency_ms: float = 0.0
    by_category: dict[str, dict] = field(default_factory=dict)
    mechanisms: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_mechanisms": self.total_mechanisms,
            "auto_wired": self.auto_wired,
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
            "total_latency_ms": round(self.total_latency_ms, 3),
            "by_category": self.by_category,
            "mechanisms": self.mechanisms,
        }


def _instance_of(entry: dict) -> BaseMechanism | None:
    data = entry.get("data", {}) or {}
    inst = data.get("executable") or data.get("instance")
    if isinstance(inst, BaseMechanism):
        return inst
    return None


def collect_registry_metrics(registry: Any) -> MetricsSnapshot:
    """遍历 registry 所有机制, 汇总 meta() + 运行时指标.

    Args:
        registry: MechanismRegistry 实例(或含 _mechanisms 的对象)

    Returns:
        MetricsSnapshot: 全量机制指标聚合
    """
    snap = MetricsSnapshot()
    entries = getattr(registry, "_mechanisms", {})
    for name, entry in entries.items():
        inst = _instance_of(entry)
        if inst is None:
            # 纯元数据机制(无实例)也计数, 但无运行指标
            snap.total_mechanisms += 1
            continue

        snap.total_mechanisms += 1
        if getattr(inst, "auto_wire", False):
            snap.auto_wired += 1

        m = inst.meta()
        metrics = m.get("metrics", {})
        snap.total_calls += metrics.get("call_count", 0)
        snap.total_errors += metrics.get("error_count", 0)
        snap.total_latency_ms += metrics.get("total_latency_ms", 0.0)

        cat = m.get("category", "general")
        if cat not in snap.by_category:
            snap.by_category[cat] = {"count": 0, "calls": 0, "errors": 0, "latency_ms": 0.0}
        snap.by_category[cat]["count"] += 1
        snap.by_category[cat]["calls"] += metrics.get("call_count", 0)
        snap.by_category[cat]["errors"] += metrics.get("error_count", 0)
        snap.by_category[cat]["latency_ms"] += metrics.get("total_latency_ms", 0.0)

        snap.mechanisms.append({
            "name": m.get("name", name),
            "category": cat,
            "phase": m.get("phase"),
            "auto_wire": m.get("auto_wire"),
            "invoke_count": m.get("invoke_count", 0),
            "fitness": m.get("fitness", 0.0),
            "metrics": metrics,
        })

    return snap


def export_prometheus_format(snap: MetricsSnapshot) -> str:
    """导出为 Prometheus text exposition 格式(零依赖, 宿主可 /metrics 暴露).

    指标:
      nexus_mechanism_calls_total{category,mechanism}
      nexus_mechanism_errors_total{category,mechanism}
      nexus_mechanism_latency_ms_total{category,mechanism}
    """
    lines: list[str] = []
    for m in snap.mechanisms:
        cat = m["category"]
        nm = m["name"]
        met = m["metrics"]
        lines.append(
            f'nexus_mechanism_calls_total{{category="{cat}",mechanism="{nm}"}} {met.get("call_count", 0)}'
        )
        lines.append(
            f'nexus_mechanism_errors_total{{category="{cat}",mechanism="{nm}"}} {met.get("error_count", 0)}'
        )
        lines.append(
            f'nexus_mechanism_latency_ms_total{{category="{cat}",mechanism="{nm}"}} {round(met.get("total_latency_ms", 0.0), 3)}'
        )
    return "\n".join(lines)


__all__ = [
    "MetricsSnapshot",
    "collect_registry_metrics",
    "export_prometheus_format",
]
