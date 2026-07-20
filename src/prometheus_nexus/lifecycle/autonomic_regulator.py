"""AutonomicRegulator — Omega 自主神经系统.

监听所有管道完成事件，分析 fitness 趋势，做出全局调节决策。
不修改任何管道的核心逻辑，只订阅 event_bus。

设计原则：
- 不阻塞任何管道执行
- 只做定量分析（fitness 差值、趋势），不做 LLM 推理
- 所有异常 try/except 保护
- 决策结果通过 event_bus publish 通知其他模块
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# fitness 趋势窗口上限: 仅保留最近 N 条记录, 防止长时运行实例(如 9200)内存无界增长,
# 同时保证降级/恢复判定只基于近期真实信号, 不被远古数据污染。
MAX_FITNESS_HISTORY = 200


class AutonomicRegulator:
    """Omega 自主神经系统——管道间自进化反馈核。

    订阅事件：
        evolve_completed  → 比较 fitness 差值 → 更新 UCB1 奖励
        learn_completed   → 检查学习效果 → 调整好奇心
        maintain_completed → 检查恢复状态 → 通报恢复

    触发动作：
        - UCB1 策略奖励（基于真实 fitness 差值）
        - 连续 fitness 下降 → 触发 self_healing + 降级事件
        - 连续 learn 空结果 → 调整好奇心方向
        - 喂入 thermodynamic 数据
    """

    def __init__(self, omega: Any):
        self._omega = omega
        self._fitness_log: list[tuple[float, float, str]] = []
        self._strategy_results: dict[str, list[float]] = defaultdict(list)
        self._consecutive_zero_gain = 0

    def subscribe(self, bus: Any) -> None:
        """订阅全部 7 管道完成事件。"""
        if hasattr(bus, "subscribe"):
            bus.subscribe("evolve_completed", self._on_evolve, priority=0.9)
            bus.subscribe("learn_completed", self._on_learn, priority=0.7)
            bus.subscribe("maintain_completed", self._on_maintain, priority=0.6)
            bus.subscribe("reflect_completed", self._on_reflect, priority=0.5)
            bus.subscribe("recall_completed", self._on_recall, priority=0.4)
            bus.subscribe("dream_completed", self._on_dream, priority=0.3)
            bus.subscribe("remember_completed", self._on_remember, priority=0.2)
            bus.subscribe("rumination_completed", self._on_rumination, priority=0.6)
            bus.subscribe("capability_consumed", self._on_capability, priority=0.6)
            logger.info("AutonomicRegulator subscribed to 7 event types")

    def _on_reflect(self, event: dict) -> None:
        """reflect 完成后——检查系统自检质量。"""
        try:
            data = event.get("data", {})
            # 类型边界修复(cycle-30): 合法 0.0 是最差反思分, 绝不能被 `or 0.5` 误掩为 0.5
            # (否则 `score < 0.4` 退化检测对真实零分永不触发)。仅缺失/显式 None 才回退 0.5。
            raw_score = data.get("composite_score", 0.5)
            score = float(raw_score) if raw_score is not None else 0.5
            drift_count = len(data.get("drift_alerts", [])) if isinstance(data.get("drift_alerts"), (list, tuple)) else (data.get("drift_alerts", 0) or 0)
            # Low reflect score + high drift → system in decline
            if score < 0.4 and drift_count > 2:
                self._consecutive_zero_gain += 1
                if self._consecutive_zero_gain >= 2:
                    logger.info("AR: consecutive low reflect scores, adjusting curiosity")
            else:
                self._consecutive_zero_gain = 0
        except Exception as e:
            logger.warning("AR._on_reflect: %s", e)

    def _on_recall(self, event: dict) -> None:
        """recall 完成后——检查召回质量。"""
        try:
            data = event.get("data", {})
            hits = data.get("hits", 0) or 0
            # Zero-hits recall may indicate knowledge gap
            if hits == 0:
                logger.debug("AR: recall returned 0 hits")
        except Exception as e:
            logger.warning("AR._on_recall: %s", e)

    def _on_dream(self, event: dict) -> None:
        """dream 完成后——检查模式发现质量。"""
        try:
            data = event.get("data", {})
            patterns = data.get("patterns_found", 0) or 0
            beliefs = data.get("beliefs_synthesized", 0) or 0
            if patterns == 0 and beliefs == 0:
                logger.debug("AR: dream found no patterns")
        except Exception as e:
            logger.warning("AR._on_dream: %s", e)

    def _on_remember(self, event: dict) -> None:
        """remember 完成后——记录写操作。"""
        try:
            data = event.get("data", {})
            _ = data.get("status", "?")
        except Exception as e:
            logger.warning("AR._on_remember: %s", e)

    def _on_rumination(self, event: dict) -> None:
        """反刍完成 → 记录知新产出到 fitness 趋势，供熔断/降级判断。"""
        try:
            d = event.get("data", {})
            promoted = d.get("skills_promoted", 0) or 0
            routed = d.get("routed_nodes", 0) or 0
            if promoted > 0 or routed > 0:
                self._fitness_log.append((max(0.1, 0.5 + 0.01 * promoted), time.time(), "rumination"))
                if len(self._fitness_log) > MAX_FITNESS_HISTORY:
                    self._fitness_log = self._fitness_log[-MAX_FITNESS_HISTORY:]
        except Exception as e:
            logger.warning("AutonomicRegulator._on_rumination: %s", e)

    def _on_capability(self, event: dict) -> None:
        """机制被宿主消费(emit/apply) → 正 fitness 信号；被拒 → 负信号。"""
        try:
            d = event.get("data", {})
            accepted = d.get("accepted", False)
            fit = 0.5 + (0.05 if accepted else -0.05)
            self._fitness_log.append((max(0.05, fit), time.time(), "capability"))
            if len(self._fitness_log) > MAX_FITNESS_HISTORY:
                self._fitness_log = self._fitness_log[-MAX_FITNESS_HISTORY:]
        except Exception as e:
            logger.warning("AutonomicRegulator._on_capability: %s", e)

    def _on_evolve(self, event: dict) -> None:
        """evolve 完成后——比较 fitness 变化，更新策略奖励。"""
        try:
            data = event.get("data", {})
            before = data.get("fitness_before", 0.5)
            after = data.get("fitness_after", 0.5)
            delta = after - before
            strategy = data.get("strategy", "default")

            self._fitness_log.append((after, time.time(), "evolve"))
            if len(self._fitness_log) > MAX_FITNESS_HISTORY:
                self._fitness_log = self._fitness_log[-MAX_FITNESS_HISTORY:]
            self._strategy_results[strategy].append(delta)

            # 1. 用真实差值更新 UCB1 奖励（不再用假的正数奖励）
            reward = max(-1.0, min(1.0, delta * 10))
            self._omega.ucb1.update(strategy, max(0.0, reward + 1.0))

            # 如果策略真让系统变差 — 记录 fitness 到反进化门供回归检测
            if delta < -0.05:
                try:
                    self._omega.anti_evolution.record_score(after)
                except Exception as e:
                    logger.warning("AR: record_score failed: %s", e)

            # 反馈回路：evolve 有效性回传
            try:
                ctx = self._omega.signal_fusion.get_chain_context()
                if ctx and ctx.get("trigger_pipe") == "reflect":
                    # evolve 是由低分 reflect 触发的 — 此 evolve 有效与否是对 reflect 回诊
                    outcome = {"from": "evolve", "to": "reflect",
                               "type": "evolve_efficacy", "data": {
                                   "delta": round(delta, 4),
                                   "effective": delta > 0,
                               }}
                    self._omega.signal_fusion.push_feedback(outcome)
            except Exception:
                logger.warning("AutonomicRegulator: failed to push evolve feedback")
                pass

            # 2. 连续 fitness 下降 → 触发降级
            # 仅基于 evolve 真实 fitness (type=="evolve"), 排除 capability/rumination 合成值噪声:
            # 否则外部机制被接受(0.55)/反刍产出会伪造"连续下降", 误触降级 + 熔断 + 外部进化(隐藏真实薄弱)。
            evolve_recent = [v for (v, _, t) in self._fitness_log if t == "evolve"][-5:]
            if len(evolve_recent) >= 3 and all(evolve_recent[i] < evolve_recent[i-1] for i in range(1, len(evolve_recent))):
                self._trigger_downgrade(f"fitness_decline: {evolve_recent}")
                # ===== P0b 熔断门: 连续下降时回滚最近激活的机制(解 B3 僵尸机制无监管) =====
                # 坏机制激活后若拖垮 fitness, 自动 deactivate (而非永久驻留 _enabled)
                self._circuit_break_active_mechanisms()
                # ===== S7: 四轨调度 — 进化停滞 → 触发 T3/T4 超前探索 =====
                self._trigger_external_evolution(recent[-1])

            # 3. 进化长期无增益(停滞) → 同样触发外部探索
            if len(self._fitness_log) >= 10:
                last10 = [f for f, _, _ in self._fitness_log[-10:]]
                if max(last10) - min(last10) < 0.01:
                    self._trigger_external_evolution(recent[-1])

            # 3. 喂入 thermodynamic
            try:
                self._omega.thermodynamic.observe_action(
                    action=f"evolve:{strategy[:12]}",
                    outcome_valid=delta > 0,
                    rarity=max(0.01, abs(delta)),
                )
            except Exception:
                logger.warning("AutonomicRegulator: failed to record evolve thermodynamic observation")
                pass

        except Exception as e:
            logger.warning("AutonomicRegulator._on_evolve: %s", e)

    def _on_learn(self, event: dict) -> None:
        """learn 完成后——评估学习效果。"""
        try:
            data = event.get("data", {})
            new_nodes = data.get("new_nodes", 0)

            if new_nodes == 0:
                self._consecutive_zero_gain += 1
            else:
                self._consecutive_zero_gain = 0

            # 连续 3 次 learn 都无收获 → 换方向
            if self._consecutive_zero_gain >= 3:
                try:
                    self._omega.curiosity_queue.add(
                        "Find a new topic (previous 3 attempts yielded nothing)",
                        priority=10,
                    )
                except Exception:
                    logger.warning("AutonomicRegulator: failed to add curiosity topic")
                    pass
                self._consecutive_zero_gain = 0

            # 观察 learn 结果
            try:
                self._omega.thermodynamic.observe_action(
                    action="learn",
                    outcome_valid=new_nodes > 0,
                    rarity=max(0.01, new_nodes / 10),
                )
            except Exception:
                logger.warning("AutonomicRegulator: failed to record learn thermodynamic observation")
                pass

        except Exception as e:
            logger.warning("AutonomicRegulator._on_learn: %s", e)

    def _on_maintain(self, event: dict) -> None:
        """maintain 完成后——检查恢复状态。"""
        try:
            # 仅基于 evolve 真实 fitness 判断恢复, 排除 capability/rumination 合成值噪声
            evolve_recent = [v for (v, _, t) in self._fitness_log if t == "evolve"][-3:]
            if len(evolve_recent) >= 2 and evolve_recent[-1] > evolve_recent[0]:
                # fitness 在上升 → 系统恢复中
                self._omega.event_bus.publish({
                    "type": "system_recovered",
                    "fitness": evolve_recent[-1],
                })
        except Exception as e:
            logger.warning("AutonomicRegulator._on_maintain: %s", e)

    def _trigger_downgrade(self, reason: str) -> None:
        """触发系统降级。"""
        try:
            self._omega.self_healing.heal({"reason": reason})

            self._omega.event_bus.publish({
                "type": "system_downgrade",
                "reason": reason,
                "fitness": self._fitness_log[-1][0] if self._fitness_log else 0.5,
            })

            try:
                self._omega.thermodynamic.observe_action(
                    action="downgrade",
                    outcome_valid=True,
                    rarity=0.05,
                )
            except Exception:
                logger.warning("AutonomicRegulator: failed to record downgrade thermodynamic observation")
                pass

            logger.info("AutonomicRegulator: triggered downgrade — %s", reason)
        except Exception as e:
            logger.warning("AutonomicRegulator._trigger_downgrade: %s", e)

    def _circuit_break_active_mechanisms(self) -> int:
        """P0b/P1 C3: 熔断门 — fitness 连续下降时精准回滚有害外部机制.

        精准化(修正 V2 矫枉过正): 只回滚确证有害的机制, 不泛化回滚所有 T3/T4:
        - consume_error: 消费(emit/inject)时抛异常 -> 机制本身有问题
        - emit_accepted is False: 宿主明确拒绝接收(机制对宿主无价值)
        - consumed_at is None: 激活后从未被消费(僵尸, 无人接)
        正常的 T3(注入 gene 后被适应度评估)不在此列, 避免误伤好机制.
        """
        rolled = 0
        try:
            reg = getattr(self._omega, "mechanism_registry", None)
            if reg is None:
                return 0
            for name in list(reg.get_enabled()):
                entry = reg._mechanisms.get(name, {})
                cat = entry.get("category", "")
                if cat not in ("compiled", "extracted", "compilation_pending", "extraction_pending"):
                    continue  # 只处理外部进化机制
                harmful = (
                    entry.get("consume_error")
                    or entry.get("emit_accepted") is False
                    or entry.get("consumed_at") is None
                )
                if harmful and reg.deactivate(name):
                    rolled += 1
                    logger.warning("AR: circuit-break deactivated %s (fitness decline, harmful=%s)", name, harmful)
                    try:
                        self._omega.anti_evolution.record_score(entry.get("activated_at", 0.0) or 0.0)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("AR: circuit_break failed: %s", e)
        return rolled

    def _trigger_external_evolution(self, current_fitness: float) -> None:
        """S7: 进化停滞/下降时, 触发 T3(借成熟机制)/T4(编译新机制) 超前探索。

        策略:
        - 优先 T3: 从焦点主题(focus_topics)对应的成熟 GitHub 项目提取机制
        - 备选 T4: 若焦点主题命中论文源, 编译新机制草案
        两者都只 register 进 MechanismRegistry(候选), 不直替生产, 由验证门+A-B 并行决定激活。
        """
        try:
            omega = self._omega
            # T3: 用 focus_topics 里的高频主题作为 github 搜索 query 提取机制
            topics = list(getattr(omega, "focus_topics", {}) or {})
            triggered_t3 = 0
            if topics and hasattr(omega, "mechanism_extractor"):
                for topic in topics[:2]:
                    # 注意: 真实提取需网络拉 repo; 此处触发"待提取"标记, 由外部调度拉取
                    omega.mechanism_registry.register(
                        f"t3_pending_{topic}",
                        data={"trigger": "external_evolution", "topic": topic, "rail": "T3"},
                        category="extraction_pending",
                    )
                    triggered_t3 += 1
            # T4: 标记论文编译待处理
            triggered_t4 = 0
            if hasattr(omega, "mechanism_compiler"):
                omega.mechanism_registry.register(
                    "t4_pending_explore",
                    data={"trigger": "external_evolution", "rail": "T4",
                          "fitness": current_fitness},
                    category="compilation_pending",
                )
                triggered_t4 += 1
            logger.info("AR: external evolution triggered (T3=%d T4=%d)", triggered_t3, triggered_t4)
        except Exception as e:
            logger.warning("AutonomicRegulator._trigger_external_evolution: %s", e)

    def get_stats(self) -> dict:
        """获取调节器统计。"""
        return {
            "fitness_log_size": len(self._fitness_log),
            "strategies_tracked": dict(self._strategy_results),
            "consecutive_zero_gain": self._consecutive_zero_gain,
        }
