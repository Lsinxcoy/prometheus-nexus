"""TelemetryPipeline — 感觉皮层：将管道诊断数据转化为结构化信号。

问题：7管道产生121次诊断写入，0个消费者。
原因：每个管道将机制级数据写入 dict，但dict仅作为返回值的装饰性元数据
      返回给调用者。事件总线不传输这些数据，订阅者（CNS/CC/AR）完全不知道。

解决方案：在管道与CC/CNS/AR之间加一层结构化遥测总线。
  1. 每个管道执行完成后，Omega 将完整返回值存入 self._telemetry["pipe_name"]
  2. TelemetryPipeline 收到事件后，从 self._telemetry 读取原始返回值
  3. 按信号模式提取关键维度，结构化存储
  4. 供 CC/CNS/AR 通过 self._omega.telemetry.query() 查询

不修改任何管道代码。只在 life.py 每个管道返回点前加 1 行存储。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SignalSnapshot:
    """某管道某次执行的结构化信号快照。"""
    pipeline: str = ""
    timestamp: float = 0.0
    signals: dict[str, Any] = field(default_factory=dict)
    raw_metadata: dict = field(default_factory=dict)
    trigger_chain_id: str = ""


class TelemetryPipeline:
    """感觉皮层 — 管道信号解析与结构化存储。

    收到管道完成事件后，读取 Omega 中存储的原始返回值，
    按 _SIGNAL_SCHEMA 提取结构化信号维度，供 CC/CNS/AR 查询。

    用法:
        bus.subscribe("evolve_completed", telemetry._on_event, ...)
        # 之后：
        last = telemetry.query("evolve")  # 最近一次信号
        trend = telemetry.query("evolve", window=5)  # 最近5次趋势
    """

    # 各管道的信号提取模式
    # key: 信号名 → (提取路径, 值类型)
    # 提取路径: "return.field.subfield" 或 "return.metadata.diagnostics_key"
    # 值类型: "n"=数值, "bool", "categorical", "avg"=均值
    _PIPE_SCHEMAS: dict[str, dict[str, tuple[str, str]]] = {
        "remember": {
            "node_utility": ("event.data.utility", "n"),      # 来自 event data: publish 传了 utility
            "node_id": ("event.data.node_id", "categorical"), # 发布时传了 node_id
            "tag_count": ("event.data.tags", "len"),           # 来自 event data: publish 传了 list(tags)
        },
        "recall": {
            "hit_count": ("return.total_count", "n"),
            "query": ("return.query", "categorical"),
            "duration_ms": ("return.duration_ms", "n"),
            "avg_score": ("return.metadata", "avg"),
        },
        "evolve": {
            "fitness_before": ("return.fitness_before", "n"),
            "fitness_after": ("return.fitness_after", "n"),
            "delta": ("return", "delta"),
            "result_code": ("return.result", "categorical"),
            "duration_ms": ("return.duration_ms", "n"),
            "best_strategy": ("return.metadata", "best_strategy"),
            "gate_block_count": ("return.metadata", "gate_block_count"),
            "consensus_rate": ("return.metadata", "consensus_rate"),
            "speculative_flag": ("return.metadata", "speculative_flag"),
        },
        "learn": {
            "new_nodes": ("return.new_nodes", "n"),
            "source": ("return.source", "categorical"),
            "applied_changes": ("return.applied_changes", "n"),
            "has_dispatched": ("return.parallel_dispatch", "has"),
        },
        "reflect": {
            "composite_score": ("return.five_view.score", "n"),
            "grade": ("return.five_view.grade", "categorical"),
            "drift_alerts": ("return.drift_alerts", "n"),
            "thermo_entropy": ("return.thermodynamic.entropy", "n"),
            "converged": ("return.convergence", "bool"),
            "worst_count": ("return.worst_performers", "n"),
        },
        "dream": {
            "patterns_found": ("return.patterns_found", "n"),
            "beliefs": ("return.beliefs_synthesized", "n"),
            "connections": ("return.connections_discovered", "n"),
            "insight_count": ("return.insights", "len"),
        },
        "maintain": {
            "duration_ms": ("return.duration_ms", "n"),
            "decayed_nodes": ("return.expired_nodes", "n"),
            "traj_actions": ("return.trajectory_actions", "n"),
            "benchmark_avail": ("return.benchmark", "has"),
        },
        "rumination": {
            "total_scanned": ("event.data.total_scanned", "n"),
            "relearned": ("event.data.relearned", "n"),
            "mappings_applied": ("event.data.mappings_applied", "n"),
            "skills_promoted": ("event.data.skills_promoted", "n"),
            "routed_nodes": ("event.data.routed_nodes", "n"),
            "utility_raised": ("event.data.utility_raised", "n"),
            "pending_t3": ("event.data.pending_t3", "n"),
            "pending_t4": ("event.data.pending_t4", "n"),
        },
    }

    def __init__(self, omega: Any) -> None:
        self._omega = omega
        self._history: dict[str, list[SignalSnapshot]] = {
            p: [] for p in self._PIPE_SCHEMAS
        }
        self._max_window = 50  # 每管道最大保留条数

    def subscribe(self, bus: Any) -> None:
        """订阅全部 7 管道完成事件。"""
        if not hasattr(bus, "subscribe"):
            logger.warning("TelemetryPipeline: bus has no subscribe method")
            return
        for pipe in self._PIPE_SCHEMAS:
            bus.subscribe(f"{pipe}_completed", self._on_event, priority=0.95)
        logger.info("TelemetryPipeline subscribed to %d pipe events",
                     len(self._PIPE_SCHEMAS))

    def record(self, metric: str, value: float) -> None:
        """记录指标（兼容API）。"""
        # 将metric解析为管道名和信号名
        parts = metric.split(".", 1)
        pipe = parts[0] if len(parts) > 0 else "unknown"
        signal = parts[1] if len(parts) > 1 else "value"
        
        if pipe in self._history:
            snapshot = SignalSnapshot(
                pipeline=pipe,
                timestamp=time.time(),
                signals={signal: value},
                source="manual_record"
            )
            self._history[pipe].append(snapshot)
            # 限制窗口大小
            if len(self._history[pipe]) > self._max_window:
                self._history[pipe] = self._history[pipe][-self._max_window:]

    def get_health(self) -> dict:
        """获取系统健康状态。"""
        health = {"status": "healthy", "metrics": []}
        for pipe, history in self._history.items():
            if history:
                latest = history[-1]
                health["metrics"].append({
                    "pipe": pipe,
                    "signals": latest.signals,
                    "timestamp": latest.timestamp
                })
        return health

    def _on_event(self, event: dict) -> None:
        """收到事件 → 提取信号 → 存储。"""
        try:
            data = event.get("data", {})
            event_type = data.get("type", "")
            pipe = event_type.replace("_completed", "") if event_type else ""

            if pipe not in self._PIPE_SCHEMAS:
                return

            raw = getattr(self._omega, "_telemetry", {}).get(pipe)
            signals = self._extract_signals(pipe, raw, data)

            snapshot = SignalSnapshot(
                pipeline=pipe,
                timestamp=time.time(),
                signals=signals,
                raw_metadata=_safe_dict(getattr(raw, "metadata", {}) if hasattr(raw, "metadata")
                                         else (raw if isinstance(raw, dict) else {})),
            )

            history = self._history[pipe]
            history.append(snapshot)
            if len(history) > self._max_window:
                # 保留完整窗口容量(与 record() 及文档 max_window='每管道最大保留条数' 一致);
                # 旧实现 self._max_window // 2 仅保留半数, 生产路径静默丢失一半遥测历史。
                self._history[pipe] = history[-self._max_window:]

        except Exception as e:
            logger.warning("TelemetryPipeline._on_event: %s", e)

    def _extract_signals(self, pipe: str, raw: Any, event_data: dict) -> dict[str, Any]:
        """按模式提取信号。"""
        schema = self._PIPE_SCHEMAS.get(pipe, {})
        signals: dict[str, Any] = {}

        for name, (path, typ) in schema.items():
            try:
                value = self._resolve(path, raw, event_data, name)
                signals[name] = self._coerce(value, typ)
            except Exception:
                signals[name] = None

        return signals

    def _resolve(self, path: str, raw: Any, event_data: dict, name: str) -> Any:
        """按路径解析值。"""
        if path == "return" and hasattr(raw, "result"):
            # 特殊：从 EvolutionOutcome 算 delta
            if name == "delta":
                return getattr(raw, "fitness_after", 0.0) - getattr(raw, "fitness_before", 0.0)
            return raw

        if path == "return.total_count":
            return getattr(raw, "total_count", 0) if hasattr(raw, "total_count") else 0
        if path == "return.duration_ms":
            return getattr(raw, "duration_ms", 0.0) if hasattr(raw, "duration_ms") else 0.0
        if path == "return.fitness_before":
            return getattr(raw, "fitness_before", 0.0)
        if path == "return.fitness_after":
            return getattr(raw, "fitness_after", 0.0)
        if path == "return.result":
            val = getattr(raw, "result", "")
            return val.value if hasattr(val, "value") else str(val)
        if path == "return.patterns_found":
            if hasattr(raw, "patterns_found"):
                return raw.patterns_found
            return event_data.get("patterns", 0)
        if path == "return.beliefs_synthesized":
            if hasattr(raw, "beliefs_synthesized"):
                return raw.beliefs_synthesized
            return event_data.get("beliefs", 0)
        if path == "return.connections_discovered":
            if hasattr(raw, "connections_discovered"):
                return raw.connections_discovered
            return event_data.get("connections", 0)
        if path == "return.insights":
            return getattr(raw, "insights", [])
        if path == "return.metadata":
            meta = getattr(raw, "metadata", {}) if hasattr(raw, "metadata") else (
                raw if isinstance(raw, dict) else {})
            if name == "avg_score" and isinstance(meta, dict):
                scores = [h.get("score", 0) for h in meta.get("route_stats", {})]
                return sum(scores) / max(len(scores), 1) if scores else None
            if name == "best_strategy" and isinstance(meta, dict):
                diag = meta.get("diagnostics", {})
                if isinstance(diag, dict):
                    bs = meta.get("best_strategy", "") or diag.get("best_strategy", "")
                    if bs:
                        return bs
                    td = diag.get("trace_decision", {})
                    return td.get("best_strategy", "") if isinstance(td, dict) else ""
                return meta.get("best_strategy", "")
            if name == "gate_block_count" and isinstance(meta, dict):
                diag = meta.get("diagnostics", {})
                if isinstance(diag, dict):
                    count = 0
                    for k, v in diag.items():
                        if "block" in k.lower() or "gate" in k.lower():
                            if isinstance(v, (int, float)) and v > 0:
                                count += v
                    return count
                return 0
            if name == "consensus_rate" and isinstance(meta, dict):
                diag = meta.get("diagnostics", {}) or {}
                cv = diag.get("camp_vote", 0)
                cp = diag.get("camp_panel", 0)
                if cp and cv is not None:
                    return round(cv / max(cp, 1), 3)
                return None
            if name == "speculative_flag" and isinstance(meta, dict):
                diag = meta.get("diagnostics", {}) or {}
                return bool(diag.get("speculative_result") or diag.get("speculative_fork_merge"))
            return meta

        if path == "return.query":
            return getattr(raw, "query", "")
        if path == "return.five_view.score":
            fv = raw.get("five_view", {}) if isinstance(raw, dict) else {}
            return fv.get("score", 0.5)
        if path == "return.five_view.grade":
            fv = raw.get("five_view", {}) if isinstance(raw, dict) else {}
            return fv.get("grade", "C")
        if path == "return.drift_alerts":
            return raw.get("drift_alerts", 0) if isinstance(raw, dict) else 0
        if path == "return.thermodynamic.entropy":
            td = raw.get("thermodynamic", {}) if isinstance(raw, dict) else {}
            return td.get("entropy", 0.0)
        if path == "return.convergence":
            return bool(raw.get("convergence", False) if isinstance(raw, dict) else False)
        if path == "return.worst_performers":
            return raw.get("worst_performers", 0) if isinstance(raw, dict) else 0
        if path == "return.new_nodes":
            return raw.get("new_nodes", 0) if isinstance(raw, dict) else 0
        if path == "return.source":
            return raw.get("source", "") if isinstance(raw, dict) else ""
        if path == "return.applied_changes":
            return raw.get("applied_changes", 0) if isinstance(raw, dict) else 0
        if path == "return.parallel_dispatch":
            d = raw.get("parallel_dispatch", {}) if isinstance(raw, dict) else {}
            return bool(d.get("dispatched", 0) > 0)
        if path == "return.expired_nodes":
            return raw.get("expired_nodes", 0) if isinstance(raw, dict) else 0
        if path == "return.trajectory_actions":
            return raw.get("trajectory_actions", 0) if isinstance(raw, dict) else 0
        if path == "return.benchmark":
            b = raw.get("benchmark", {}) if isinstance(raw, dict) else {}
            return bool(b)

        # event.data.* 通用路径 — 从 event_data dict 读取字段
        if path.startswith("event.data."):
            field = path[len("event.data."):]
            return event_data.get(field)

        return None

    @staticmethod
    def _coerce(value: Any, typ: str) -> Any:
        """类型强制转换。"""
        if value is None:
            return None
        if typ == "n":
            return float(value) if not isinstance(value, (int, float)) else float(value)
        if typ == "bool":
            return bool(value)
        if typ == "categorical":
            return str(value)
        if typ == "delta":
            return float(value)
        if typ == "avg":
            return float(value) if value is not None else None
        if typ == "len":
            return len(value) if isinstance(value, (list, dict, str)) else 0
        if typ == "has":
            return bool(value)
        return value

    # ─────────────────────────────────────────────
    # 公共查询 API
    # ─────────────────────────────────────────────

    def query(self, pipeline: str, window: int = 1) -> list[SignalSnapshot] | SignalSnapshot | None:
        """查询管道的信号快照。

        Args:
            pipeline: 管道名（remember/recall/evolve/learn/reflect/dream/maintain）
            window: 1=返回最近一条，N=返回最近N条

        Returns:
            window=1 时返回 SignalSnapshot 或 None
            window>1 时返回 list[SignalSnapshot]
        """
        history = self._history.get(pipeline, [])
        if not history:
            return None if window == 1 else []

        if window == 1:
            return history[-1]

        return history[-window:]

    def last_signal(self, pipeline: str, signal: str) -> Any:
        """快速获取某管道最新某信号值。"""
        snap = self.query(pipeline)
        if snap is None:
            return None
        return snap.signals.get(signal)

    def trend(self, pipeline: str, signal: str, window: int = 10) -> list[float]:
        """获取某信号的趋势序列。"""
        snaps = self.query(pipeline, window)
        if not snaps:
            return []
        values = [s.signals.get(signal) for s in snaps if s.signals.get(signal) is not None]
        return [float(v) for v in values if v is not None]

    def get_state(self) -> dict:
        """获取遥测状态摘要。"""
        summary = {}
        for pipe, history in self._history.items():
            if history:
                last = history[-1]
                summary[pipe] = {
                    "snapshots": len(history),
                    "last_signals": list(last.signals.keys()),
                    "last_ts": last.timestamp,
                }
            else:
                summary[pipe] = {"snapshots": 0}
        return summary


def _safe_dict(d: Any) -> dict:
    """递归安全的 dict 提取（用于日志，只保留第一层）。"""
    if isinstance(d, dict):
        return {k: v for k, v in d.items()
                if isinstance(v, (str, int, float, bool, type(None)))}
    return {}
