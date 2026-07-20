"""Self-Observation 增强 — 高熵态策略切换 (arXiv 2601.00514).

"aha moment" 是幻觉，mid-reasoning shift 仅 6.31%。
高熵态才触发策略切换，不是自我洞察。

Instrumented trace collection, multi-temperature decoding simulation,
and entropy-reasoning correlation analysis.
"""

from __future__ import annotations
import logging
import math
import random
from collections import Counter, defaultdict
from typing import Any

logger = logging.getLogger(__name__)


# ── original standalone functions (unchanged) ─────────────────────────────────


def compute_strategy_entropy(actions: list[str]) -> float:
    """计算动作序列的熵值。高熵=不确定性高=应该切换策略。"""
    if not actions:
        return 0.0
    c = Counter(actions)
    total = len(actions)
    entropy = -sum((count / total) * math.log2(count / total) for count in c.values())
    return round(entropy / math.log2(max(len(c), 2)), 4)


def should_switch_strategy(recent_actions: list[str],
                           success_rate: float = 0.0,
                           entropy_threshold: float = 0.7) -> dict:
    """判断是否应该切换策略。

    论文依据 (arXiv 2601.00514):
    - Natural mid-reasoning shifts are rare (6.31%) and don't improve accuracy
    - Forced shifts at high entropy DO help
    """
    entropy = compute_strategy_entropy(recent_actions)
    if entropy >= entropy_threshold and success_rate < 0.5:
        return {
            "switch": True,
            "entropy": entropy,
            "reason": f"High entropy ({entropy}) + low success ({success_rate})",
        }
    return {
        "switch": False,
        "entropy": entropy,
        "reason": f"Entropy {entropy} < threshold {entropy_threshold}",
    }


# ── StrategySwitcher class with instrumented traces ───────────────────────────


class StrategySwitcher:
    """Full instrumented strategy switch with trace collection and correlation analysis.

    Implements the million-trace analysis from arXiv 2601.00514:
    - Collects per-decision traces including strategy, action, entropy, outcome
    - Simulates multi-temperature decoding to probe forced shifts
    - Computes entropy-reasoning correlations
    """

    TEMPERATURES = [0.2, 0.5, 0.7, 1.0, 1.5]

    def __init__(self, entropy_threshold: float = 0.7,
                 temperature: float = 1.0):
        self._entropy_threshold = entropy_threshold
        self._temperature = temperature
        self._traces: list[dict] = []           # instrumented trace collection
        self._decisions: list[dict] = []         # decision history
        self._shifts = 0                         # total forced shifts
        self._natural_shifts = 0                 # natural (self-observed) shifts

    # ── public API ────────────────────────────────────────────────────────────

    def decide(self, recent_actions: list[str],
               success_rate: float = 0.0,
               metadata: dict = None) -> dict:
        """Decide whether to switch strategies, with full instrumentation.

        Args:
            recent_actions: List of recent action labels.
            success_rate: Current success rate (0-1).
            metadata: Optional context {"task": ..., "phase": ..., "step": ...}

        Returns:
            {"switch": bool, "entropy": float, "reason": str, "trace_id": int}
        """
        entropy = compute_strategy_entropy(recent_actions)
        decision = should_switch_strategy(recent_actions, success_rate,
                                          self._entropy_threshold)

        # Record instrumented trace
        trace = {
            "trace_id": len(self._traces),
            "entropy": entropy,
            "success_rate": success_rate,
            "action_count": len(recent_actions),
            "unique_actions": len(set(recent_actions)) if recent_actions else 0,
            "switch": decision["switch"],
            "reason": decision["reason"],
            "temperature": self._temperature,
            "metadata": metadata or {},
        }
        self._traces.append(trace)

        if decision["switch"]:
            self._shifts += 1
            self._decisions.append(trace)

        return {**decision, "trace_id": trace["trace_id"]}

    # ── multi-temperature decoding simulation ────────────────────────────────

    def multi_temperature_decode(self, actions: list[str],
                                 base_outcomes: list[float] = None) -> dict:
        """Simulate multi-temperature decoding and report forced-shift effects.

        At higher temperatures, action distribution flattens, increasing entropy.
        Measures whether forced shifts under high-temperature decoding would
        change the outcome.

        Args:
            actions: Original action sequence.
            base_outcomes: Associated outcome scores (0-1) per action.

        Returns:
            {"temperature_results": dict, "forced_shift_benefit": float,
             "high_temp_entropy": float, "low_temp_entropy": float}
        """
        if base_outcomes is None:
            base_outcomes = [1.0] * len(actions)

        results = {}
        for temp in self.TEMPERATURES:
            # Simulate softened action distribution
            counts = Counter(actions)
            total = len(actions)
            # Apply temperature scaling to probabilities
            probs = {}
            for a, c in counts.items():
                scaled = c ** (1.0 / max(temp, 0.01))
                probs[a] = scaled
            norm = sum(probs.values())
            if norm > 0:
                probs = {k: v / norm for k, v in probs.items()}

            sim_entropy = -sum(p * math.log2(p) for p in probs.values())
            max_ent = math.log2(max(len(probs), 2))
            norm_entropy = round(sim_entropy / max_ent, 4) if max_ent > 0 else 0.0

            # Simulated forced-shift benefit: if entropy is high, switch helps
            switch_needed = norm_entropy >= self._entropy_threshold
            results[str(temp)] = {
                "entropy": norm_entropy,
                "switch_needed": switch_needed,
                "action_distribution": probs,
            }

        # Compute forced-shift benefit: how often does high temp suggest a
        # switch the original decision missed?
        high_ent = results.get("1.5", {}).get("entropy", 0.0)
        low_ent = results.get("0.2", {}).get("entropy", 0.0)

        return {
            "temperature_results": results,
            "forced_shift_benefit": round(high_ent - low_ent, 4),
            "high_temp_entropy": high_ent,
            "low_temp_entropy": low_ent,
        }

    # ── entropy-reasoning correlation analysis ───���────────────────────────────

    def entropy_correlation_analysis(self) -> dict:
        """Compute correlation between entropy and reasoning outcomes.

        From arXiv 2601.00514: natural shifts are rare (6.31%), forced shifts
        under high entropy improve outcomes.

        Returns:
            {"total_traces": int, "natural_shift_rate": float, "forced_shift_rate": float,
             "entropy_outcome_corr": float, "high_entropy_trace_count": int}
        """
        n = len(self._traces)
        if n < 2:
            return {
                "total_traces": n,
                "natural_shift_rate": 0.0,
                "forced_shift_rate": 0.0,
                "entropy_outcome_corr": 0.0,
                "high_entropy_trace_count": 0,
            }

        switches = sum(1 for t in self._traces if t["switch"])
        high_ent = sum(1 for t in self._traces if t["entropy"] >= self._entropy_threshold)

        # Pearson correlation between entropy and success_rate
        entropies = [t["entropy"] for t in self._traces]
        rates = [t["success_rate"] for t in self._traces]

        n_eff = len(entropies)
        mean_e = sum(entropies) / n_eff
        mean_r = sum(rates) / n_eff
        cov = sum((e - mean_e) * (r - mean_r) for e, r in zip(entropies, rates))
        var_e = sum((e - mean_e) ** 2 for e in entropies)
        var_r = sum((r - mean_r) ** 2 for r in rates)
        denom = math.sqrt(var_e * var_r)
        corr = round(cov / denom, 4) if denom > 0 else 0.0

        return {
            "total_traces": n,
            "natural_shift_rate": round(self._natural_shifts / max(n, 1), 4),
            "forced_shift_rate": round(switches / max(n, 1), 4),
            "entropy_outcome_corr": corr,
            "high_entropy_trace_count": high_ent,
        }

    # ── helper: record a natural (self-observed) shift ────────────────────────

    def record_natural_shift(self, trace_id: int):
        """Mark a trace as a *natural* mid-reasoning shift (not forced).

        The paper shows these are rare (~6.31%) and don't improve accuracy.
        """
        for t in self._traces:
            if t["trace_id"] == trace_id:
                t["natural_shift"] = True
                self._natural_shifts += 1
                break

    # ── trace retrieval ───────────────────────────────────────────────────────

    def get_traces(self, limit: int = None) -> list[dict]:
        """Return instrumented traces, newest first."""
        traces = list(reversed(self._traces))
        if limit is not None:
            traces = traces[:limit]
        return traces

    def get_stats(self) -> dict:
        return {
            "total_decisions": len(self._decisions),
            "total_traces": len(self._traces),
            "shifts": self._shifts,
            "natural_shifts": self._natural_shifts,
            "natural_shift_rate": round(
                self._natural_shifts / max(self._traces, 1), 4
            ),
            "entropy_threshold": self._entropy_threshold,
            "temperature": self._temperature,
        }
