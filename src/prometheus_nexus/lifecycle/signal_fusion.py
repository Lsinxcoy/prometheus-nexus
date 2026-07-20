# SignalFusionLayer — 信号融合层 🧬
# 
# 增强：链上下文通道 + 反馈队列
# - set_chain_context(): CNS 触发下游前，把触发管的完整信号挂到当前链
# - get_chain_context(): 下游管道读取触发管信号
# - _clean_chain_context(): chain_end 时自动清理
# - push_feedback(): 任何层可以推送反馈
# - pop_feedback(): CNS 轮询反馈

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class SignalFusionLayer:
    """信号融合层 — 统一决策者信号消费接口。

    位于 TelemetryPipeline 与 CNS/CC/AR 之间：

        CNS / CC / AR
            │  signal() / chain_analysis()
            ▼
        SignalFusionLayer
            │  telemetry.query()
            ▼
        TelemetryPipeline
            │  _telemetry[pipe]
            ▼
        7 Pipelines

    v6.2.0 增强:
    - 链上下文通道: set_chain_context / get_chain_context
    - 反馈队列: push_feedback / pop_feedback
    """

    def __init__(self, omega: Any) -> None:
        self._omega = omega

        # 链追踪 — 栈结构支持嵌套
        self._chain_stack: list[str] = []
        self._chains: dict[str, dict] = {}  # chain_id -> {trigger, snapshots: []}
        self._chain_history: list[dict] = []

        # 链上下文通道 — chain_id -> {trigger_pipe, trigger_signals, ts}
        self._chain_context: dict[str, dict] = {}

        # 管道执行结果缓存（双向语义穿透）
        self._pipe_results: dict[str, dict] = {}

        # 反馈队列 — 任何层推送的跨管道反馈
        self._feedback_queue: list[dict] = []

        # 合并反馈
        self._merge_hints: dict[str, float] = {}
        self._merge_hint_expiry: dict[str, float] = {}

        # 阈值自适应（全部 7 个）
        self._last_threshold_adjust: dict[str, float] = {}
        self._adjust_cooldown = 300
        self._invalid_count = 0  # 融合层 invalid 触发计数 (监控用)

    def subscribe(self, bus: Any) -> None:
        """订阅所有管道完成事件，用于链追踪和合并反馈。"""
        if not hasattr(bus, "subscribe"):
            logger.warning("SignalFusionLayer: bus has no subscribe method")
            return
        for suffix in ["remember", "recall", "evolve", "learn",
                        "reflect", "dream", "maintain", "rumination"]:
            bus.subscribe(f"{suffix}_completed", self._on_pipe_event, priority=0.85)
        logger.info("SignalFusionLayer subscribed to all 7 pipe events")

    # ─────────────────────────────────────────────
    # 链追踪
    # ─────────────────────────────────────────────

    def chain_start(self, trigger: str) -> str:
        """启动一条新的触发链。使用栈结构支持嵌套。"""
        cid = f"{time.time_ns()}_{uuid.uuid4().hex[:6]}"
        self._chain_stack.append(cid)
        self._chains[cid] = {
            "trigger": trigger,
            "started_at": time.time(),
            "snapshots": [],
        }
        self._trim_chains()
        return cid

    def chain_end(self, cid: str) -> None:
        """结束一条触发链。"""
        if cid in self._chains:
            self._chains[cid]["ended_at"] = time.time()
            record = self._chains.pop(cid)
            record["_cid"] = cid
            self._chain_history.append(record)
            if len(self._chain_history) > 50:
                self._chain_history = self._chain_history[-25:]
        # 从栈中移除该链
        if cid in self._chain_stack:
            self._chain_stack.remove(cid)
        # 清理链上下文
        self._clean_chain_context(cid)

    def _on_pipe_event(self, event: dict) -> None:
        """收到管道事件 → 将当前快照链接到活跃链（栈顶）。"""
        try:
            data = event.get("data", {})
            pipe = data.get("type", "").replace("_completed", "")
            if not pipe or not self._chain_stack:
                return

            active_id = self._chain_stack[-1]
            chain = self._chains.get(active_id)
            if chain is None:
                return

            snap = self._omega.telemetry.query(pipe)
            if snap is None:
                return

            chain["snapshots"].append({
                "pipe": pipe,
                "ts": time.time(),
                "signals_snapshot": snap,
            })
        except Exception as e:
            logger.warning("SignalFusionLayer._on_pipe_event: %s", e)

    def chain_analysis(self, cid: str) -> dict | None:
        """获取整条链的分析结果。"""
        chain = self._chains.get(cid)
        if chain is None:
            for h in self._chain_history:
                if h.get("_cid") == cid:
                    chain = h
                    break

        if chain is None:
            return None

        snapshots = chain.get("snapshots", [])
        delta = 0
        first_score = None
        last_score = None
        chain_pipes = []

        for snap in snapshots:
            chain_pipes.append(snap["pipe"])
            s = snap.get("signals_snapshot", {})
            if hasattr(s, "signals"):
                if snap["pipe"] == "reflect":
                    sc = s.signals.get("composite_score")
                    if first_score is None and sc is not None:
                        first_score = sc
                    last_score = sc
                elif snap["pipe"] == "evolve":
                    fb = s.signals.get("fitness_before")
                    fa = s.signals.get("fitness_after")
                    if fb is not None and fa is not None:
                        delta = fa - fb

        return {
            "chain_id": cid,
            "trigger": chain.get("trigger", ""),
            "pipes": chain_pipes,
            "duration_s": (chain.get("ended_at", time.time())
                           - chain.get("started_at", time.time())),
            "fitness": {
                "start": first_score,
                "end": last_score,
                "delta": delta,
            },
            "snapshot_count": len(snapshots),
        }

    def _trim_chains(self) -> None:
        """清理超过 1 小时且已完成或未完成的链。"""
        now = time.time()
        active_set = set(self._chain_stack)
        stale_keys = [
            k for k, v in self._chains.items()
            if now - v.get("started_at", now) > 3600
        ]
        for k in stale_keys:
            if k not in active_set:
                del self._chains[k]

    # ─────────────────────────────────────────────
    # 链上下文通道（v6.2.0）
    # ─────────────────────────────────────────────

    def set_chain_context(self, pipe: str, signals: dict) -> None:
        """CNS 在触发下游管道前调用。将触发管的完整信号挂到当前链。

        增强：自动融合 CC 洞察 + AR 健康状态到上下文中。

        Args:
            pipe: 触发管道名（如 "learn"、"reflect"）
            signals: 触发管的完整信号 dict（来自 telemetry.query 或 event data）
        """
        if not self._chain_stack:
            logger.debug("SFL: set_chain_context called with no active chain")
            return

        # Merge CC insights if available
        cc_insights = {}
        try:
            cc = self._omega.cerebral_cortex
            if hasattr(cc, 'get_insights'):
                cc_insights = cc.get_insights() or {}
        except Exception as e:
            logger.debug("SFL: CC insights merge failed: %s", e)

        # Merge AR health state if available
        ar_health = {}
        try:
            ar = self._omega.autonomic_regulator
            if hasattr(ar, 'get_stats'):
                ar_stats = ar.get_stats() or {}
                ar_health = {
                    "fitness_log_size": ar_stats.get("fitness_log_size", 0),
                    "consecutive_zero_gain": ar_stats.get("consecutive_zero_gain", 0),
                    "strategies_tracked": ar_stats.get("strategies_tracked", 0),
                }
        except Exception as e:
            logger.debug("SFL: AR health merge failed: %s", e)

        active_id = self._chain_stack[-1]
        self._chain_context[active_id] = {
            "trigger_pipe": pipe,
            "trigger_signals": signals,
            "cc_insights": cc_insights,
            "ar_health": ar_health,
            "ts": time.time(),
        }

    def get_chain_context(self) -> dict | None:
        """下游管道在开始时调用。获取触发管的结构化信号。

        Returns:
            dict: {"trigger_pipe": str, "trigger_signals": dict, "ts": float}
            没有活跃链或没有上下文时返回 None
        """
        if not self._chain_stack:
            return None
        active_id = self._chain_stack[-1]
        return self._chain_context.get(active_id)

    def _clean_chain_context(self, cid: str) -> None:
        """chain_end 时清理上下文。"""
        self._chain_context.pop(cid, None)

    # ─────────────────────────────────────────────
    # 管道执行结果存储（双向语义穿透）
    # ─────────────────────────────────────────────

    def set_pipe_result(self, pipe: str, result: dict) -> None:
        """管道在执行完毕后调用，将结果写入信号融合层。

        下游管道可以通过 get_pipe_result() 读取上游管道的执行结果。
        结果会被合并到 chain_context 中（如果存在活跃链）。

        Args:
            pipe: 管道名 (remember/recall/evolve/learn/reflect/dream/maintain)
            result: 管道返回的执行结果 dict
        """
        self._pipe_results[pipe] = {
            "result": result,
            "ts": time.time(),
        }
        # 如果存在活跃链，也合并到 chain_context
        if self._chain_stack:
            active_id = self._chain_stack[-1]
            if active_id in self._chain_context:
                self._chain_context[active_id].setdefault("pipe_results", {})[pipe] = result

    def get_pipe_result(self, pipe: str) -> dict | None:
        """上游管道的执行结果（如果有的话）。

        下游管道调用此接口读取上游管道的执行结果，
        实现双向语义穿透（不仅是 CNS→管道，还有 管道→管道）。

        Args:
            pipe: 管道名

        Returns:
            管道执行结果 dict，或 None
        """
        entry = self._pipe_results.get(pipe)
        if entry is None:
            return None
        # 5 秒内有效
        if time.time() - entry["ts"] > 5.0:
            return None
        return entry["result"]

    # ─────────────────────────────────────────────
    # 反馈队列（v6.2.0）
    # ─────────────────────────────────────────────

    def push_feedback(self, feedback: dict) -> None:
        """任何层推送跨管道反馈。

        feedback 格式: {"from": "learn", "to": "evolve",
                        "type": "quality", "data": {...}, "ts": ...}
        """
        if "ts" not in feedback:
            feedback["ts"] = time.time()
        self._feedback_queue.append(feedback)
        # 限制队列大小
        if len(self._feedback_queue) > 100:
            self._feedback_queue = self._feedback_queue[-50:]

    def pop_feedback(self, target_pipe: str) -> list[dict]:
        """CNS 或其他层轮询针对本管道的未消费反馈。

        Args:
            target_pipe: 管道名

        Returns:
            未消费的反馈列表（消费后从队列移除）
        """
        consumed = [f for f in self._feedback_queue if f.get("to") == target_pipe]
        self._feedback_queue = [f for f in self._feedback_queue
                                if f.get("to") != target_pipe]
        return consumed

    # ─────────────────────────────────────────────
    # 统一信号查询
    # ─────────────────────────────────────────────

    def get_pipe_signals(self, pipe: str) -> dict:
        """批量信号查询：返回管道的最新完整信号dict。

        作为统一信号门面，CNS/CC/AR 应使用此接口代替
        直接调用 telemetry.query() + .signals 的模式。

        Args:
            pipe: 管道名（remember/recall/evolve/learn/reflect/dream/maintain）

        Returns:
            信号 dict（最新快照的signals字段）；无数据时返回空dict
        """
        try:
            snap = self._omega.telemetry.query(pipe, window=1)
            if snap is None:
                return {}
            return getattr(snap, "signals", {}) or {}
        except Exception:
            logger.warning("SignalFusion: failed to read pipe signals, returning empty")
            return {}

    def signal(self, pipe: str, field: str,
               window: int = 1) -> Any:
        """统一信号查询接口。

        CNS/CC/AR 使用此接口代替 event.get("data", {}).get("field")。

        当前实现：委托给 telemetry.query() 作为统一信号查询后端。
        signal_fusion.signal() 是推荐入口；直接调 telemetry.query() 也可工作。

        Args:
            pipe: 管道名
            field: 信号字段名
            window: 窗口大小（1=最新值，N=平均值）

        Returns:
            信号值（window=1）或平均值（window>1）
        """
        try:
            snap = self._omega.telemetry.query(pipe, window)
            if snap is None:
                return None
            if window == 1:
                return snap.signals.get(field)

            values = [
                s.signals.get(field) for s in snap
                if s.signals.get(field) is not None
            ]
            if not values:
                return None
            return sum(float(v) for v in values) / len(values)
        except Exception as e:
            logger.debug("SignalFusionLayer.signal: %s", e)
            return None

    # ─────────────────────────────────────────────
    # 合并反馈
    # ─────────────────────────────────────────────

    def report_merge(self, pipe: str, gap_s: float,
                     suggested_interval: float = 120) -> None:
        self._merge_hints[pipe] = suggested_interval
        self._merge_hint_expiry[pipe] = time.time() + suggested_interval
        logger.info(
            "SignalFusionLayer: merge hint for %s "
            "(gap=%.1fs, interval=%.0fs)", pipe, gap_s, suggested_interval)

    def check_merge_hint(self, pipe: str) -> float:
        interval = self._merge_hints.get(pipe, 0)
        expiry = self._merge_hint_expiry.get(pipe, 0)
        if interval > 0 and time.time() < expiry:
            return interval
        self._merge_hints.pop(pipe, None)
        self._merge_hint_expiry.pop(pipe, None)
        return 0

    # ─────────────────────────────────────────────
    # 多阈值���适应建议
    # ─────────────────────────────────────────────

    def suggest_threshold(self, key: str) -> float | None:
        try:
            return self._compute_suggested_threshold(key)
        except Exception as e:
            logger.debug("SignalFusionLayer.suggest_threshold: %s", e)
            return None

    def _compute_suggested_threshold(self, key: str) -> float | None:
        if key == "reflect_to_evolve_max_score":
            reflects = self._omega.telemetry.query("reflect", 10)
            if not reflects or len(reflects) < 3:
                return None
            scores = [s.signals.get("composite_score", 0.5) for s in reflects]
            avg = sum(scores) / len(scores)
            if avg < 0.3:
                return 0.55
            elif avg < 0.4:
                return 0.50
            elif avg < 0.55:
                return 0.45
            elif avg < 0.7:
                return 0.40
            else:
                return 0.30

        if key == "reflect_to_dream_min_score":
            dreams = self._omega.telemetry.query("dream", 10)
            if not dreams or len(dreams) < 3:
                return None
            avg_patterns = sum(
                s.signals.get("patterns_found", 0) for s in dreams) / len(dreams)
            if avg_patterns < 1:
                return 0.85
            return None

        if key == "evolve_to_dream_min_delta":
            evolves = self._omega.telemetry.query("evolve", 10)
            if not evolves or len(evolves) < 3:
                return None
            deltas = [s.signals.get("delta", 0) for s in evolves
                      if s.signals.get("delta") is not None]
            if not deltas:
                return None
            avg_delta = round(sum(deltas) / len(deltas), 6)
            if avg_delta < 0.01:
                return 0.04
            if avg_delta <= 0.02:
                return 0.02
            return 0.03

        if key == "learn_to_reflect_min_nodes":
            learns = self._omega.telemetry.query("learn", 10)
            if not learns or len(learns) < 3:
                return None
            avg_nodes = sum(
                s.signals.get("new_nodes", 0) for s in learns) / len(learns)
            if avg_nodes > 4:
                return 3
            return 2

        if key == "dream_to_maintain_min_patterns":
            dreams = self._omega.telemetry.query("dream", 10)
            if not dreams or len(dreams) < 3:
                return None
            avg = sum(
                s.signals.get("patterns_found", 0) for s in dreams) / len(dreams)
            if avg < 0.5:
                return 2
            return None

        if key == "evolve_to_heal_max_delta":
            evolves = self._omega.telemetry.query("evolve", 10)
            if not evolves or len(evolves) < 3:
                return None
            deltas = [s.signals.get("delta", 0) for s in evolves
                      if s.signals.get("delta") is not None]
            if not deltas:
                return None
            min_delta = min(deltas)
            if min_delta < -0.05:
                return -0.03
            return None

        if key == "remember_reflect_interval":
            nodes = self._omega.telemetry.last_signal("remember", "node_utility")
            if nodes is None:
                return None
            return 100

        return None

    def apply_threshold_adjustments(self) -> list[dict]:
        now = time.time()
        if now - self._last_threshold_adjust.get("_last_apply", 0) < self._adjust_cooldown:
            return []

        cns = getattr(self._omega, "cns", None)
        if cns is None:
            return []

        adjustments = []
        for key in ["learn_to_reflect_min_nodes", "reflect_to_evolve_max_score",
                     "reflect_to_dream_min_score", "evolve_to_dream_min_delta",
                     "evolve_to_heal_max_delta", "dream_to_maintain_min_patterns",
                     "remember_reflect_interval"]:
            suggested = self.suggest_threshold(key)
            if suggested is None:
                continue

            if key == "reflect_to_evolve_max_score":
                try:
                    cc = getattr(self._omega, "cerebral_cortex", None)
                    if cc is not None:
                        pending = getattr(cc, "_pending_threshold", None)
                        if pending is not None:
                            suggested = min(suggested, pending)
                except Exception:
                    logger.warning("SignalFusion: failed to check pending threshold from CC")
                    pass

            old_val = cns._thresholds.get(key, 0)
            if abs(suggested - old_val) > 0.01:
                cns.update_threshold(key, suggested)
                adjustments.append({
                    "key": key,
                    "old": round(old_val, 3),
                    "new": round(suggested, 3),
                })

        self._last_threshold_adjust["_last_apply"] = now
        return adjustments

    # ─────────────────────────────────────────────
    # 公共状态
    # ─────────────────────────────────────────────

    def get_state(self) -> dict:
        return {
            "active_chains": len(self._chain_stack),
            "chain_stack_top": self._chain_stack[-1][:12] if self._chain_stack else None,
            "chains": len(self._chains),
            "chain_history": len(self._chain_history),
            "chain_contexts": len(self._chain_context),
            "feedback_queue": len(self._feedback_queue),
            "merge_hints": dict(self._merge_hints),
            "last_adjust_ts": self._last_threshold_adjust.get("_last_apply", 0),
        }
