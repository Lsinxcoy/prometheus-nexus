"""CerebralCortex — 大脑皮层: 学习型管道间调度中枢。

位于 CNSOrchestrator（反射弧）之上，为系统添加 4 条高级神经回路：

回路 A: recall → learn（知识缺口补全）
   recall 返回 0 结果 → 记录知识缺口 → 连续缺失触发 learn

回路 B: 阈值自适应（经验驱动调参）
   每次 trigger 记录 outcome → 统计成功率 → 动态调整 CNS 阈值

回路 C: 历史感知熔断（不要做没用的事）
   跟踪 trigger 类型效果 → 低效 trigger 自动暂停 → 输出建议

回路 D: 多信号合并（避免重复工作）
   短时间内同类触发合并 → 一次 reflect 处理多原因

设计原则：
- 不修改 CNS、AutonomicRegulator、7 管道中的任何代码
- 只订阅 event_bus + 通过 publish 或 CNS.update_threshold 控制
- 所有数据持久化到 store 以便跨会话学习
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class CerebralCortex:
    """大脑皮层 — 学习型管道间调度中枢。

    4 条神经回路:
    A. 知识缺口补全（recall空结果→learn）
    B. 阈值自适应（历史outcome→调参）
    C. 历史感知熔断（低效trigger自动暂停）
    D. 多信号合并（短时间同类触发去重）

    与 CNSOrchestrator / AutonomicRegulator 的关系：
    - CNS: 反射弧，执行条件触发
    - AR: 生命体征监测，UCB1/fitness趋势
    - CC: 大脑皮层，分析历史数据改进触发策略
    - 三个互补，互不修改对方代码
    """

    # 默认配置
    _DEFAULT_CONFIG = {
        # 回路 A: 知识缺口
        "gap_max_count": 3,           # 同一 query 连续 N 次空结果触发 learn
        "gap_min_interval": 300,      # 同 query learn 的最小间隔（秒）
        "gap_max_recent": 50,         # 缺口日志上限

        # 回路 B: 自适应
        "adapt_window_size": 10,      # 统计窗口大小
        "adapt_min_samples": 5,       # 最小样本数才开始调参
        "adapt_success_threshold": 0.3,   # 成功率低于此值视为低效
        "adapt_re_evaluate_interval": 600,  # 熔断后重评估间隔（秒）
        "max_outcomes_per_trigger": 20,     # 每个 trigger 类型保留的最大 outcome 数

        # 回路 C: 熔断
        "fuse_trigger": 5,            # 连续触发无效次数上限
        "fuse_history": 100,          # 决策日志上限

        # 回路 D: 合并
        "merge_window": 5,            # 合并窗口（秒）
    }

    def __init__(self, omega: Any) -> None:
        self._omega = omega
        self._config = dict(self._DEFAULT_CONFIG)

        # 回路 A: 知识缺口
        self._knowledge_gaps: dict[str, list[float]] = defaultdict(list)
        self._gap_learn_triggered: dict[str, float] = {}
        self._gap_log: list[dict] = []

        # 回路 B: 自适应
        # trigger_type -> [(fitness_at_trigger, outcome_delta, timestamp)]
        self._trigger_outcomes: dict[str, list[tuple[float, float, float]]] = defaultdict(list)

        # 回路 C: 熔断
        self._trigger_suppressed: dict[str, bool] = {}
        self._suppress_until: dict[str, float] = {}  # 重评估时间
        self._admin_log: list[dict] = []

        # 回路 D: 合并
        self._merge_buffer: dict[str, float] = {}       # trigger_type -> last_time
        self._merge_reasons: dict[str, list[str]] = defaultdict(list)

        # 阈值自适应触发器
        self._reflect_counter = 0  # reflect 次数计数
        self._pending_threshold: float | None = None  # 等待 SFL 统一写入的建议阈值

        # 回路 E: 学习质量反馈 — learn 产出 → recall 命中桥接
        self._learn_quality: dict[str, list[dict]] = defaultdict(list)  # {source:query -> [{ts, nodes, hits}]}

    def subscribe(self, bus: Any) -> None:
        """订阅事件。"""
        if not hasattr(bus, "subscribe"):
            logger.warning("CerebralCortex: bus has no subscribe method")
            return
        # 回路 A: 监听 recall 空结果
        bus.subscribe("recall_completed", self._on_recall, priority=0.8)

        # 回路 B/C: 监听各管道 outcome（扩展到全部 7 种事件）
        for suffix in ["remember", "recall", "evolve", "learn",
                        "reflect", "dream", "maintain"]:
            bus.subscribe(f"{suffix}_completed", self._on_outcome, priority=0.8)

        # 反刍知新完成 → 记录 outcome（与 evolve/learn 同口径参与自适应/熔断）
        bus.subscribe("rumination_completed", self._on_rumination, priority=0.7)

        # 回路 D: 监听 trigger 型事件
        bus.subscribe("reflect_completed", self._on_reflect, priority=0.9)
        bus.subscribe("dream_completed", self._on_dream, priority=0.8)

        logger.info("CerebralCortex subscribed: gap_detection, 7-pipe outcomes, fusing, merging")

    # ─────────────────────────────────────────────
    # 回路 A: 知识缺口补全
    # ─────────────────────────────────────────────

    def _on_recall(self, event: dict) -> None:
        """recall 空结果 → 记录知识缺口 → 连续缺失触发 learn。
        有结果时 → 记录 learn 质量反馈（如果该 query 来源于 learn）。"""
        try:
            data = event.get("data", {})
            query = data.get("query", "")
            hits = data.get("hits", 0)

            if hits > 0 and query:
                # 有结果 → 检查是否命中 learn 产出的知识
                try:
                    for key in list(self._learn_quality.keys()):
                        # key = "source:query", 模糊匹配
                        if query in key or key in query or key.split(":", 1)[-1] in query:
                            self._learn_quality[key].append({
                                "hit": True,
                                "query": query,
                                "hits": hits,
                                "ts": time.time(),
                            })
                            # 保持大小
                            if len(self._learn_quality[key]) > 20:
                                self._learn_quality[key] = self._learn_quality[key][-10:]
                except Exception:
                    logger.warning("CerebralCortex: failed to register learn quality data")
                    pass
                return  # 有结果，不记录缺口

            if not query:
                return  # 空查询，不做事

            now = time.time()
            gaps = self._knowledge_gaps[query]

            # 清理超时缺口（超过 1 小时的旧缺口）
            self._knowledge_gaps[query] = [t for t in gaps if now - t < 3600]

            # 添加新缺口
            self._knowledge_gaps[query].append(now)

            # 检查是否需要触发 learn
            if len(self._knowledge_gaps[query]) >= self._config["gap_max_count"]:
                last_learn = self._gap_learn_triggered.get(query, 0)
                if now - last_learn >= self._config["gap_min_interval"]:
                    if self._trigger_knowledge_gap_learn(query):
                        self._gap_learn_triggered[query] = now
                        self._knowledge_gaps[query] = []

            # 日志
            self._gap_log.append({
                "query": query,
                "gap_count": len(self._knowledge_gaps[query]),
                "ts": now,
            })
            if len(self._gap_log) > self._config["gap_max_recent"]:
                self._gap_log = self._gap_log[-self._config["gap_max_recent"] // 2:]

        except Exception as e:
            logger.warning("CerebralCortex._on_recall: %s", e)

    def _trigger_knowledge_gap_learn(self, query: str) -> bool:
        """触发 learn 补全知识缺口，并绕过配额检查（知识缺口优先）。
        Returns: True=learn 成功调用，False=learn 失败。
        """
        try:
            logger.info("CerebralCortex: knowledge gap detected for '%s', triggering learn", query)
            # 直接调用 learn，不检查 quota
            self._omega.learn(source="web", query=query, max_results=3)
            return True
        except Exception as e:
            logger.warning("CerebralCortex: gap learn failed for '%s': %s", query, e)
            return False

    # ─────────────────────────────────────────────
    # 回路 B: 阈值自适应 + 回路 C: 历史感知熔断
    # ─────────────────────────────────────────────

    def _on_outcome(self, event: dict) -> None:
        """监听管道完成事件，记录 trigger outcome 用于自适应和熔断。

        现在通过 SignalFusionLayer 的结构化信号代替原始 event data。
        订阅全部 7 种事件但只处理 evolve 和 learn（其他管道不需要 outcome 跟踪）。
        """
        try:
            data = event.get("data", {})
            event_type = event.get("topic", data.get("type", ""))

            # 处理全部 7 个管道完成事件以扩展熔断覆盖
            if event_type == "evolve_completed":
                try:
                    sf = getattr(self._omega, "signal_fusion", None)
                    if sf is not None:
                        before = sf.signal("evolve", "fitness_before")
                        after = sf.signal("evolve", "fitness_after")
                        if before is not None and after is not None:
                            delta = after - before
                            self._record_outcome("evolve", before, delta)
                            return
                except Exception:
                    logger.warning("CerebralCortex: signal_fusion unavailable for evolve outcome")
                    pass
                before = data.get("fitness_before", 0.5)
                after = data.get("fitness_after", 0.5)
                delta = after - before
                self._record_outcome("evolve", before, delta)

            elif event_type == "learn_completed":
                new_nodes = data.get("new_nodes", 0)
                outcome = min(1.0, new_nodes / 5.0)
                fitness = self._omega._compute_fitness() if hasattr(self._omega, '_compute_fitness') else 0.5
                self._record_outcome("learn", fitness, outcome)
                try:
                    source = data.get("source", "?")
                    query = data.get("query", "?")
                    self.register_learn_for_quality(source, query, new_nodes)
                except Exception:
                    logger.warning("CerebralCortex: failed to register learn quality")
                    pass

            # New handlers for remaining 5 pipes — track fitness delta/score for fuse logic
            elif event_type == "reflect_completed":
                raw_score = data.get("composite_score", 0.5)
                # 类型边界修复(cycle-41, 同 cycle-30): 合法 0.0 是最差反思分, 绝不能被 `or 0.5` 误掩为 0.5
                score = float(raw_score) if raw_score is not None else 0.5
                drift = len(data.get("drift_alerts", [])) if isinstance(data.get("drift_alerts"), (list, tuple)) else (data.get("drift_alerts", 0) or 0)
                # Drift count > 3 means reflect quality is degrading
                outcome = max(0.0, min(1.0, 1.0 - drift / 10.0))
                self._record_outcome("reflect", score, outcome)

            elif event_type == "recall_completed":
                hits = data.get("hits", 0) or 0
                avg_score = data.get("avg_score", 0.0) or 0.0
                gap = data.get("gap_empty", True)
                outcome = avg_score * 0.7 + (0.3 if not gap else 0.0)
                self._record_outcome("recall", hits / max(hits, 1), outcome)

            elif event_type == "dream_completed":
                patterns = data.get("patterns", 0) or 0
                beliefs = data.get("beliefs", 0) or 0
                outcome = min(1.0, (patterns + beliefs) / 10.0)
                self._record_outcome("dream", patterns, outcome)

            elif event_type == "remember_completed":
                raw_utility = data.get("utility", 0.5)
                # 类型边界修复(cycle-41, 同 cycle-30): 合法 0.0 记忆效用最差, 绝不能被 `or 0.5` 误掩
                utility = float(raw_utility) if raw_utility is not None else 0.5
                self._record_outcome("remember", utility, utility - 0.3)

            elif event_type == "maintain_completed":
                expired = data.get("decayed", 0) or 0
                heartbeat = data.get("heartbeat", False)
                outcome = 0.8 if heartbeat else 0.3
                self._record_outcome("maintain", 1.0 - min(1.0, expired / 100.0), outcome)

        except Exception as e:
            logger.warning("CerebralCortex._on_outcome: %s", e)

    def _on_rumination(self, event: dict) -> None:
        """反刍产出 → 记录到 outcome（与 evolve/learn 同口径参与自适应/熔断）。"""
        try:
            d = event.get("data", {})
            promoted = d.get("skills_promoted", 0) or 0
            routed = d.get("routed_nodes", 0) or 0
            outcome = min(1.0, (promoted + routed) / 10.0)
            fitness = self._omega._compute_fitness() if hasattr(self._omega, "_compute_fitness") else 0.5
            self._record_outcome("rumination", fitness, outcome)
        except Exception as e:
            logger.warning("CerebralCortex._on_rumination: %s", e)

    def _record_outcome(self, trigger_type: str, fitness: float, delta: float) -> None:
        """记录 trigger 的 outcome 到历史并推送反馈。"""
        now = time.time()
        outcomes = self._trigger_outcomes[trigger_type]

        # 保持窗口大小
        if len(outcomes) >= self._config["max_outcomes_per_trigger"] * 2:
            outcomes.pop(0)

        outcomes.append((fitness, delta, now))

        # 推送反馈到 CNS：这个管道的执行结果
        effective = delta > 0
        try:
            sf = getattr(self._omega, "signal_fusion", None)
            if sf is not None:
                sf.push_feedback({
                    "from": trigger_type,
                    "to": trigger_type,
                    "type": "quality" if effective else "efficacy",
                    "data": {
                        "fitness": round(fitness, 4),
                        "delta": round(delta, 4),
                        "effective": effective,
                        "source": "cc_outcome",
                    },
                })
        except Exception as e:
            logger.debug("CC: push_feedback failed: %s", e)

        # 检查熔断
        self._check_fuse(trigger_type)

        # 尝试自适应调参（如果已熔断则不调整）
        if not self._trigger_suppressed.get(trigger_type, False):
            self._adapt_threshold_if_needed(trigger_type)

    def _check_fuse(self, trigger_type: str) -> None:
        """检查是否需要熔断该 trigger 类型。"""
        outcomes = self._trigger_outcomes[trigger_type]
        if len(outcomes) < self._config["fuse_trigger"]:
            return

        recent = outcomes[-self._config["fuse_trigger"]:]
        # 统计无效 outcome 比例
        if trigger_type == "evolve":
            invalid_count = sum(1 for _, delta, _ in recent if delta <= 0)
        else:
            invalid_count = sum(1 for _, delta, _ in recent if delta <= 0.01)

        if invalid_count >= self._config["fuse_trigger"] - 1:
            # 连续 N 次无效 → 熔断
            self._trigger_suppressed[trigger_type] = True
            self._suppress_until[trigger_type] = time.time() + self._config["adapt_re_evaluate_interval"]
            self._admin_log.append({
                "action": "fuse",
                "trigger_type": trigger_type,
                "reason": f"{invalid_count}/{len(recent)} recent outcomes invalid",
                "ts": time.time(),
            })
            logger.info("CerebralCortex: fuse engaged for '%s' (%d/%d invalid)",
                        trigger_type, invalid_count, len(recent))
            # 监控计数: 熔断触发次数 (供 get_pipeline_health 读取)
            try:
                hc = getattr(self._omega, "_health_counters", None)
                if hc is None:
                    self._omega._health_counters = {}
                    hc = self._omega._health_counters
                hc["fuse_invalid"] = hc.get("fuse_invalid", 0) + 1
            except Exception:
                pass

    def _adapt_threshold_if_needed(self, trigger_type: str) -> None:
        """基于历史 outcome 计算建议阈值（不直接写 CNS，由 SFL 统一写入）。"""
        outcomes = self._trigger_outcomes[trigger_type]
        if len(outcomes) < self._config["adapt_min_samples"]:
            return

        # 计算当前 fitness 区间的成功率
        window = self._config["adapt_window_size"]
        recent = outcomes[-window:]
        success_rate = sum(1 for _, d, _ in recent if d > 0) / len(recent)

        if trigger_type != "evolve":
            return

        # 只有 evolve 有 CNS 阈值可以调
        successes = [f for f, d, _ in recent if d > 0]
        failures = [f for f, d, _ in recent if d <= 0]

        if not successes:
            return

        avg_success_fitness = sum(successes) / len(successes)
        current_fitness = outcomes[-1][0] if outcomes else 0.5

        # 计算建议阈值（存入 _pending_threshold，等待 SFL 统一写入）
        new_threshold = self._compute_evolve_threshold(current_fitness, success_rate, avg_success_fitness)
        # 比较时处理 _pending_threshold 未初始化的情况
        old = self._pending_threshold
        if old is None:
            old = getattr(self._omega.cns, "_thresholds", {}).get("reflect_to_evolve_max_score", 0.5)

        if abs(new_threshold - old) > 0.02:
            self._pending_threshold = new_threshold

    def _compute_evolve_threshold(self, current_fitness: float,
                                  success_rate: float, avg_success_fitness: float) -> float:
        """基于当前状态计算最优 evolve 阈值。

        核心逻辑：
        - 低 fitness（< 0.4）：需要积极 evolve，阈值保持在 0.5
        - 中等 fitness（0.4-0.7）：evolve 成功率低，阈值上调减少触发
        - 高 fitness（> 0.7）：极少需要 evolve，阈值设为 0.3
        - 历史成功率也影响：成功率低 → 提高阈值（减少触发）
        """
        base = 0.5

        # 根据 fitness 水平调整
        if current_fitness < 0.3:
            base = 0.55  # 极低 fitness，更积极 evolve
        elif current_fitness < 0.4:
            base = 0.50
        elif current_fitness < 0.55:
            base = 0.45  # 中等偏下，稍微收紧
        elif current_fitness < 0.7:
            base = 0.40  # 中等，减少 evolve
        else:
            base = 0.30  # 高 fitness，极少 evolve

        # 用成功率微调
        if success_rate < 0.2:
            base += 0.10  # 成功率低，更保守
        elif success_rate < 0.4:
            base += 0.05
        elif success_rate > 0.7:
            base -= 0.05  # 成功率高，可以更积极

        return max(0.25, min(0.65, base))

    def should_suppress_trigger(self, trigger_type: str) -> bool:
        """外部（CNS）调用来检查某个 trigger 是否被暂停。"""
        if not self._trigger_suppressed.get(trigger_type, False):
            return False
        # 检查是否到重评估时间
        until = self._suppress_until.get(trigger_type, 0)
        if time.time() >= until:
            self._trigger_suppressed[trigger_type] = False
            # 清除 outcome 窗口，防止 unfuse 后立即重新熔断
            self._trigger_outcomes.pop(trigger_type, None)
            self._admin_log.append({
                "action": "unfuse",
                "trigger_type": trigger_type,
                "ts": time.time(),
            })
            logger.info("CerebralCortex: unfuse '%s' (re-evaluation period elapsed)", trigger_type)
            return False
        return True

    # ─────────────────────────────────────────────
    # 回路 D: 多信号合并
    # ─────────────────────────────────────────────

    def _on_reflect(self, event: dict) -> None:
        """监听 reflect 完成，记录其触发原因用于合并。每3次 reflect 触发一次阈值自适应。"""
        try:
            data = event.get("data", {})
            score = data.get("composite_score", 0.5)
            now = time.time()

            # 每 3 次 reflect 触发一次阈值自适应
            self._reflect_counter += 1
            if self._reflect_counter % 3 == 0:
                try:
                    sf = getattr(self._omega, "signal_fusion", None)
                    if sf is not None:
                        sf.apply_threshold_adjustments()
                except Exception as e:
                    logger.warning("CC._on_reflect: apply_threshold failed: %s", e)

            # 检查 5 秒内是否有多个信号
            if self._merge_buffer.get("last_reflect", 0) > 0:
                gap = now - self._merge_buffer["last_reflect"]
                if gap < self._config["merge_window"]:
                    self._admin_log.append({
                        "action": "merge_detected",
                        "gap_s": round(gap, 1),
                        "reasons": list(self._merge_reasons["reflect"]),
                        "ts": now,
                    })
                    # 通知 SignalFusionLayer 合并提示
                    try:
                        self._omega.signal_fusion.report_merge(
                            "reflect", gap, suggested_interval=120)
                    except Exception:
                        logger.warning("CerebralCortex: failed to report merge to signal_fusion")
                        pass
                    logger.debug("CerebralCortex: merged reflect (%d triggers in %.1fs)",
                                 len(self._merge_reasons["reflect"]), gap)

            self._merge_buffer["last_reflect"] = now
        except Exception as e:
            logger.warning("CerebralCortex._on_reflect: %s", e)

    def _on_dream(self, event: dict) -> None:
        """监听 dream 完成，合并短时间内的 dream 请求。"""
        try:
            now = time.time()
            gap = now - self._merge_buffer.get("last_dream", 0)
            if gap < self._config["merge_window"] and gap > 0:
                self._admin_log.append({
                    "action": "merge_detected",
                    "type": "dream",
                    "gap_s": round(gap, 1),
                    "ts": now,
                })
            self._merge_buffer["last_dream"] = now
        except Exception as e:
            logger.warning("CerebralCortex._on_dream: %s", e)

    def add_merge_reason(self, pipeline: str, reason: str) -> None:
        """外部调用（如 CNS）添加合并原因。"""
        self._merge_reasons[pipeline].append(reason)
        if len(self._merge_reasons[pipeline]) > 10:
            self._merge_reasons[pipeline] = self._merge_reasons[pipeline][-5:]

    def is_duplicate(self, pipeline: str, min_interval: float = 30.0) -> bool:
        """检查某个管道是否在短时间内被多次触发（去重辅助）。"""
        last = self._merge_buffer.get(pipeline, 0)
        now = time.time()
        if now - last < min_interval:
            return True
        self._merge_buffer[pipeline] = now
        return False

    # ─────────────────────────────────────────────
    # 回路 A 公开 API（供 CNS 调用，避免直接访问私有属性）
    # ─────────────────────────────────────────────

    def get_gap_count(self, query: str) -> int:
        """公开接口：获取指定 query 的活跃缺口数（自动清理超时缺口）。"""
        now = time.time()
        gaps = self._knowledge_gaps.get(query, [])
        gaps = [t for t in gaps if now - t < 3600]
        self._knowledge_gaps[query] = gaps
        return len(gaps)

    def record_gap(self, query: str) -> None:
        """公开接口：记录一次知识缺口。"""
        self._knowledge_gaps[query].append(time.time())

    def check_and_trigger_gap_learn(self, query: str) -> bool:
        """公开接口：检查缺口是否达到阈值，如果是则触发 learn。
        Returns: True 表示触发了 learn（缺口已清空），False 表示尚未达到阈值或 learn 失败。
        数据完整性：仅当 _trigger_knowledge_gap_learn 返回 True 时才清空缺口。
        """
        now = time.time()
        gap_max = self._config.get("gap_max_count", 3)
        if len(self._knowledge_gaps.get(query, [])) >= gap_max:
            last_learn = self._gap_learn_triggered.get(query, 0)
            if now - last_learn >= self._config.get("gap_min_interval", 300):
                if self._trigger_knowledge_gap_learn(query):
                    self._gap_learn_triggered[query] = now
                    self._knowledge_gaps[query] = []
                    return True
                return False
        return False

    # ─────────────────────────────────────────────
    # 公共 API
    # ─────────────────────────────────────────────

    def get_insights(self) -> dict:
        """获取大脑皮层分析洞察。"""
        now = time.time()

        # 知识缺口
        active_gaps = {
            q: len(ts_list)
            for q, ts_list in self._knowledge_gaps.items()
            if ts_list
        }

        # 熔断状态
        fuse_state = {}
        for t, suppressed in self._trigger_suppressed.items():
            remaining = max(0, self._suppress_until.get(t, 0) - now)
            fuse_state[t] = {
                "suppressed": suppressed,
                "remaining_s": round(remaining, 1) if suppressed else 0,
            }

        # 阈值状态
        current_threshold = 0.5
        try:
            current_threshold = self._omega.cns._thresholds.get("reflect_to_evolve_max_score", 0.5)
        except Exception:
            logger.warning("CerebralCortex: failed to read CNS threshold")
            pass

        # 成功率统计
        success_rates = {}
        for t, outcomes in self._trigger_outcomes.items():
            if not outcomes:
                continue
            window = self._config["adapt_window_size"]
            recent = outcomes[-window:]
            success = sum(1 for _, d, _ in recent if d > 0)
            success_rates[t] = round(success / len(recent), 2) if recent else 0

        return {
            "knowledge_gaps": active_gaps,
            "fuse_state": fuse_state,
            "evolve_threshold": round(current_threshold, 3),
            "success_rates": success_rates,
            "admin_log_entries": len(self._admin_log),
            "recent_admin_log": self._admin_log[-5:] if self._admin_log else [],
            "gap_log_entries": len(self._gap_log),
            "learn_quality": self.get_learn_quality_report(),
        }

    # ─────────────────────────────────────────────
    # 回路 E: 学习质量反馈 API
    # ─────────────────────────────────────────────

    def register_learn_for_quality(self, source: str, query: str, new_nodes: int) -> None:
        """learn 管道调用：注册本次 learn 产出，供后续 recall 命中评估。

        在每个 learn 管道执行完成后调用。
        """
        key = f"{source}:{query}"
        self._learn_quality[key].append({
            "new_nodes": new_nodes,
            "ts": time.time(),
            "hit": False,  # 初始标记未命中
        })
        # 限制大小
        if len(self._learn_quality) > 30:
            keys = sorted(self._learn_quality.keys())[:-15]
            for k in keys:
                del self._learn_quality[k]
        for k in list(self._learn_quality.keys()):
            if len(self._learn_quality[k]) > 20:
                self._learn_quality[k] = self._learn_quality[k][-10:]

    def get_learn_quality_report(self) -> list[dict]:
        """返回学习质量报告：每个 source:query 的 recall 命中率。"""
        report = []
        for key, outcomes in self._learn_quality.items():
            total = len(outcomes)
            recall_hits = sum(1 for o in outcomes if o.get("hit"))
            new_nodes = sum(o.get("new_nodes", 0) for o in outcomes
                           if not o.get("hit") or o.get("new_nodes", 0) > 0)
            hit_rate = recall_hits / max(total, 1)
            report.append({
                "key": key,
                "recall_hit_rate": round(hit_rate, 2),
                "total_entries": total,
                "recall_hits": recall_hits,
                "new_nodes": new_nodes,
            })
        return sorted(report, key=lambda r: -r["recall_hit_rate"])
