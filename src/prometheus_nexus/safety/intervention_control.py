"""InterventionController — 干预导向风险控制 (arXiv 2606.21399).

论文核心方法：
标量风险预测不是正确的控制目标。
监督应从"agent 多可能失败"转向"干预是否改善结果"。
基于反事实推理：如果干预 X，结果会改善多少？
"""

from __future__ import annotations
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


class InterventionController:
    """干预控制器——基于预期改善选择动作。"""

    def __init__(self):
        self._interventions: list[dict] = []
        self._total = 0
        self._improvement_history: list[float] = []

    def intervene(self, state: dict, actions: list[dict]) -> dict:
        """选择能最大化预期改善的动作。

        Args:
            state: 当前状态，含 {"risk_score": float, "error_count": int, "success_rate": float, ...}
            actions: 候选动作列表，每个含 {"action": str, "expected_value": float, "cost": float, ...}

        Returns:
            {"recommended_action": str, "expected_improvement": float, "reasoning": str}
        """
        self._total += 1
        if not actions:
            return {"recommended_action": "", "expected_improvement": 0.0, "reasoning": "no actions"}

        # 基线：什么都不做的预期结果
        baseline_risk = state.get("risk_score", 0.5)

        best_action = None
        best_improvement = -float("inf")

        for action in actions:
            action_name = action.get("action", "")
            expected_value = action.get("expected_value", 0.0)
            cost = action.get("cost", 0.0)
            confidence = action.get("confidence", 0.5)

            # 预期改善 = (基线风险降低 + 期望价值) × 置信度 - 成本
            risk_reduction = baseline_risk * 0.3  # 假设干预可降低 30% 风险
            improvement = (risk_reduction + expected_value) * confidence - cost

            if improvement > best_improvement:
                best_improvement = improvement
                best_action = action_name

        if best_action is None:
            return {"recommended_action": "", "expected_improvement": 0.0, "reasoning": "no viable action"}

        result = {
            "recommended_action": best_action,
            "expected_improvement": round(max(0.0, best_improvement), 4),
            "reasoning": f"baseline_risk={baseline_risk:.2f}, expected_improvement={best_improvement:.4f}",
        }
        self._interventions.append(result)
        self._improvement_history.append(best_improvement)

        return result

    def get_stats(self) -> dict:
        if not self._interventions:
            return {"total": 0, "avg_improvement": 0.0, "best_action": ""}
        avg_imp = sum(self._improvement_history) / len(self._improvement_history)
        best_action = max(self._interventions, key=lambda r: r["expected_improvement"])["recommended_action"]
        return {
            "total": self._total,
            "avg_improvement": round(avg_imp, 4),
            "best_action": best_action,
        }

    # ── Counterfactual Prefix Branching (arXiv 2606.21399 §3) ────────────────

    def prefix_branching(self, trajectory_state: dict,
                         candidate_actions: list[dict],
                         horizon: int = 3) -> dict:
        """Counterfactual prefix branching protocol.

        Paper (arXiv 2606.21399 §3.1-3.2):
        Instead of a scalar risk prediction, evaluate each candidate action by
        branching *from the same trajectory state*, simulating a short rollout
        of *horizon* steps, and computing the *intervention advantage* over the
        no-intervention baseline.

        Args:
            trajectory_state: current state dict with keys like:
                {"risk_score": float, "error_count": int, "success_rate": float,
                 "step_index": int, "total_steps": int, ...}
            candidate_actions: list of action dicts, each:
                {"action": str, "expected_value": float, "cost": float,
                 "confidence": float (optional, default 0.5)}
            horizon: number of lookahead steps to simulate (default 3)

        Returns:
            {
                "branches": [
                    {
                        "action": str,
                        "intervention_advantage": float,
                        "counterfactual_risk": float,
                        "lookahead_trace": list[dict],
                        "branch_confidence": float,
                    }, ...
                ],
                "recommended_action": str,
                "best_advantage": float,
                "baseline_risk": float,
            }
        """
        if not candidate_actions:
            return {"branches": [], "recommended_action": "",
                    "best_advantage": 0.0,
                    "baseline_risk": trajectory_state.get("risk_score", 0.5)}

        baseline_risk = trajectory_state.get("risk_score", 0.5)
        error_count = trajectory_state.get("error_count", 0)
        success_rate = trajectory_state.get("success_rate", 0.5)

        branches = []
        for action in candidate_actions:
            action_name = action.get("action", "")
            expected_value = action.get("expected_value", 0.0)
            cost = action.get("cost", 0.0)
            confidence = action.get("confidence", 0.5)

            # ── Counterfactual rollout simulation ──
            # Simulate *horizon* steps after taking this action in the same state
            lookahead_trace = []
            sim_risk = baseline_risk
            for step in range(horizon):
                # Each step: risk decays if action is corrective, grows if harmful
                if cost > 0.3:
                    # High-cost interventions reduce risk each step
                    sim_risk *= (1.0 - 0.15 * confidence)
                elif expected_value > 0.5:
                    # High-value actions also reduce risk
                    sim_risk *= (1.0 - 0.1 * confidence)
                else:
                    # Low-value, no-cost: risk drifts back toward baseline
                    sim_risk = sim_risk + (baseline_risk - sim_risk) * 0.2

                lookahead_trace.append({
                    "step": step + 1,
                    "simulated_risk": round(max(0.0, min(1.0, sim_risk)), 4),
                    "action": action_name,
                })

            counterfactual_risk = max(0.0, min(1.0, sim_risk))

            # ── Intervention advantage ──
            # Advantage = (baseline_risk - counterfactual_risk)
            #           + expected_value * confidence
            #           - cost * (1 - success_rate)
            risk_reduction = baseline_risk - counterfactual_risk
            advantage = (
                risk_reduction * 0.5  # weight on risk reduction
                + expected_value * confidence * 0.3  # weight on value
                - cost * (1.0 - success_rate) * 0.2  # penalty for cost
            )

            # Confidence in this branch: higher if the action's own confidence
            # is high AND the counterfactual shows clear improvement
            branch_confidence = confidence * (0.5 + 0.5 * min(1.0, max(0.0, risk_reduction * 2)))

            branches.append({
                "action": action_name,
                "intervention_advantage": round(advantage, 4),
                "counterfactual_risk": round(counterfactual_risk, 4),
                "lookahead_trace": lookahead_trace,
                "branch_confidence": round(branch_confidence, 4),
            })

        # Sort by advantage descending
        branches.sort(key=lambda b: -b["intervention_advantage"])
        best = branches[0]

        return {
            "branches": branches,
            "recommended_action": best["action"],
            "best_advantage": best["intervention_advantage"],
            "baseline_risk": round(baseline_risk, 4),
        }
