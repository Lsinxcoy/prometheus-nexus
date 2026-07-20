"""FiveGates — Cascading gate system with dynamic thresholds.

基于:
- "Adaptive Threshold Control for Memory Filtering" + Omega五门管道
  - 效用门: utility ≥ dynamic_min_utility
  - 惊奇门: surprise ≤ dynamic_max_surprise
  - 内容门: content非空
  - 容量门: node_count < max_nodes
  - 标签门: 默认通过

算法:
    evaluate(node, context):
        1. 获取动态阈值(基于历史utility/surprise)
        2. 五门依次检查
        3. 全部通过→记录pass历史
        4. 自适应调整阈值(pass_rate>0.9→提高; <0.3→降低)

    _adapt_thresholds():
        1. 最近20次通过率>0.9 → min_utility += 0.01
        2. 最近20次通过率<0.3 → min_utility -= 0.01

来源: Omega系统 five_gates 级联门控 + MiMo动态阈值机制
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


from prometheus_nexus.foundation.schema import CascadeResult, GateCheckResult, Node


class FiveGates:
    """5-gate cascade for memory writes with dynamic thresholds.

    Enhanced with adaptive threshold adjustment.

    Usage:
        gates = FiveGates(adaptive=True)
        cascade = gates.evaluate(node, {"current_node_count": 100})
        if not cascade.passed:
            print("Blocked")
    """

    def __init__(self, config=None, dopamine_gate=None, adaptive: bool = False):
        self._cfg = config or type('C', (), {
            'max_nodes': 100_000, 'min_utility': 0.1, 'max_surprise': 0.7  # 【P2修复】从1.0降到0.7
        })()
        self._dopamine = dopamine_gate
        self._adaptive = adaptive
        self._evaluated = 0
        self._passed = 0
        self._node_count = 0
        self._total_utility = 0.0
        self._total_surprise = 0.0
        self._current_min_utility = self._cfg.min_utility
        self._current_max_surprise = self._cfg.max_surprise  # 初始为配置值
        self._pass_history: list[bool] = []
        self._utility_history: list[float] = []
        self._surprise_history: list[float] = []

    def evaluate(self, node: Node, context: dict | None = None) -> CascadeResult:
        self._evaluated += 1

        self._utility_history.append(node.utility)
        self._surprise_history.append(node.surprise)
        if len(self._utility_history) > 100:
            self._utility_history = self._utility_history[-50:]
        if len(self._surprise_history) > 100:
            self._surprise_history = self._surprise_history[-50:]

        min_util = self._get_dynamic_threshold("min_utility", self._current_min_utility)
        max_surp = self._get_dynamic_threshold("max_surprise", self._current_max_surprise)

        checks = [
            GateCheckResult(passed=node.utility >= min_util, gate_name="utility", score=node.utility),
            GateCheckResult(passed=node.surprise <= max_surp, gate_name="surprise", score=node.surprise),
            GateCheckResult(passed=bool(node.content), gate_name="content"),
            GateCheckResult(
                passed=(context or {}).get("current_node_count", 0) < self._cfg.max_nodes,
                gate_name="capacity",
            ),
            GateCheckResult(passed=True, gate_name="tags"),
        ]

        all_passed = all(c.passed for c in checks)
        if all_passed:
            self._passed += 1

        self._pass_history.append(all_passed)
        if len(self._pass_history) > 100:
            self._pass_history = self._pass_history[-50:]

        if self._adaptive:
            self._adapt_thresholds()

        return CascadeResult(passed=all_passed, gates_checked=len(checks), details=checks)

    def _get_dynamic_threshold(self, name: str, default: float) -> float:
        # The effective threshold is `default`. In adaptive mode this carries
        # the value maintained by _adapt_thresholds() — which raises/lowers
        # self._current_min_utility from the recent pass-rate (contract:
        # pass_rate>0.9 -> raise, pass_rate<0.3 -> lower). A previous
        # history-mean branch (avg*0.3 / avg*1.5) shadowed that adaptation:
        # once the utility/surprise history reached 10 samples it overrode the
        # adapted value, so _adapt_thresholds() became a dead no-op after warm-up
        # and the gate never tightened/loosened as documented. We now always
        # consult the adapted threshold.
        return default

    def _adapt_thresholds(self):
        if len(self._pass_history) < 20:
            return

        recent_rate = sum(self._pass_history[-20:]) / 20

        if recent_rate > 0.9:
            self._current_min_utility = min(0.5, self._current_min_utility + 0.01)
        elif recent_rate < 0.3:
            self._current_min_utility = max(0.05, self._current_min_utility - 0.01)

    def register_node(self, node: Node):
        self._node_count += 1
        self._total_utility += node.utility
        self._total_surprise += node.surprise

    def get_stats(self) -> dict:
        return {
            "evaluated": self._evaluated,
            "passed": self._passed,
            "pass_rate": self._passed / max(self._evaluated, 1),
            "registered_nodes": self._node_count,
            "avg_utility": self._total_utility / max(self._node_count, 1),
            "avg_surprise": self._total_surprise / max(self._node_count, 1),
            "current_min_utility": self._current_min_utility,
            "adaptive": self._adaptive,
        }
