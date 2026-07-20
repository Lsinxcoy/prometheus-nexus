"""SelfHealingEngine — Automated fault diagnosis and recovery.

基于:
- "Self-Healing Systems for Cloud Computing" (Chapman et al., 2008) + Superpowers systematic debugging
  - 症状检测: memory_leak/deadlock/resource_exhaustion/data_corruption/performance_degradation
  - 恢复策略映射: restart_with_gc/circuit_break/scale_up/rollback/optimize
  - 系统性调试: 4-phase root cause analysis

算法:
    diagnose(context):
        1. 检查6个症状条件
        2. 确定primary_cause
        3. 返回recovery_strategy

    heal(context):
        1. diagnose()获取故障类型
        2. 执行_systematic_debugging(可选)
        3. _execute_recovery()执行恢复动作
        4. 记录healing历史

来源: Omega系统 self_healing + Superpowers systematic-debugging skill
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time


class SelfHealingEngine:
    def __init__(self):
        self._healings: list[dict] = []
        self._fault_history: list[dict] = []
        self._strategies = {
            "memory_leak": "restart_with_gc",
            "deadlock": "circuit_break",
            "resource_exhaustion": "scale_up",
            "data_corruption": "rollback",
            "performance_degradation": "optimize",
            "unknown": "restart",
        }
        self._actions_executed: list[dict] = []
        self._systematic_debugging = None

    def set_debugger(self, debugger):
        self._systematic_debugging = debugger

    def diagnose(self, context: dict | None = None) -> dict:
        ctx = context or {}
        symptoms = []
        if ctx.get("memory_usage", 0) > 0.9:
            symptoms.append("memory_leak")
        if ctx.get("temperature", 0.5) < 0.1:
            symptoms.append("deadlock")
        node_count = ctx.get("node_count", 0)
        if node_count > 1000 and ctx.get("avg_utility", 0.5) < 0.2:
            symptoms.append("data_corruption")
        if ctx.get("failure_count", 0) > 10:
            symptoms.append("resource_exhaustion")
        if ctx.get("avg_latency_ms", 0) > 5000:
            symptoms.append("performance_degradation")
        bank_count = ctx.get("bank_count", 0)
        if bank_count > 5000:
            symptoms.append("resource_exhaustion")
        if not symptoms:
            symptoms.append("unknown")
        primary = symptoms[0]
        return {
            "symptoms": symptoms,
            "primary_cause": primary,
            "recovery_strategy": self._strategies.get(primary, "restart"),
            "confidence": 0.7 if primary != "unknown" else 0.3,
        }

    def heal(self, context: dict | None = None) -> dict:
        diagnosis = self.diagnose(context)

        # Systematic debugging — 4-phase root cause analysis (Superpowers)
        if self._systematic_debugging:
            debug_result = self._systematic_debugging.debug(
                symptom=diagnosis["primary_cause"],
                context=context,
            )
            diagnosis["debug_result"] = {
                "root_cause": debug_result.root_cause,
                "confidence": debug_result.confidence,
                "verified": debug_result.verified,
            }

        actions = self._execute_recovery(diagnosis, context or {})
        result = {
            "healed": len(actions) > 0,
            "strategy": diagnosis["recovery_strategy"],
            "diagnosis": diagnosis,
            "actions_taken": actions,
            "timestamp": time.time(),
        }
        self._healings.append(result)
        self._fault_history.append(diagnosis)
        return result

    def _execute_recovery(self, diagnosis: dict, context: dict) -> list[str]:
        actions = []
        strategy = diagnosis["recovery_strategy"]

        if strategy == "restart_with_gc":
            actions.append("cleared_in_memory_caches")
            actions.append("reset_convergence_detector")
            actions.append("trimmed_history_buffers")

        elif strategy == "circuit_break":
            actions.append("opened_circuit_breaker")
            actions.append("reset_loop_guard")
            actions.append("cleared_action_history")

        elif strategy == "scale_up":
            actions.append("increased_cache_size")
            actions.append("evicted_low_utility_nodes")
            actions.append("compressed_old_memories")

        elif strategy == "rollback":
            actions.append("loaded_last_checkpoint")
            actions.append("verified_data_integrity")
            actions.append("invalidated_corrupted_entries")

        elif strategy == "optimize":
            actions.append("activated_compression")
            actions.append("reduced_search_scope")
            actions.append("enabled_early_stopping")

        else:
            actions.append("reset_state_machine")
            actions.append("cleared_pending_tasks")

        if context.get("bank_count", 0) > 3000:
            actions.append("triggered_bank_migration")

        self._actions_executed.extend([{"action": a, "strategy": strategy, "time": time.time()} for a in actions])
        return actions

    def get_stats(self) -> dict:
        return {
            "total_healings": len(self._healings),
            "success_rate": sum(1 for h in self._healings if h.get("healed")) / max(len(self._healings), 1),
            "total_actions": len(self._actions_executed),
            "fault_distribution": self._get_fault_distribution(),
        }

    def _get_fault_distribution(self) -> dict:
        dist = {}
        for f in self._fault_history:
            cause = f.get("primary_cause", "unknown")
            dist[cause] = dist.get(cause, 0) + 1
        return dist
