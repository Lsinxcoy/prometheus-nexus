"""FiveViewEvaluator — 5-view comprehensive evaluation.

基于:
- "Multi-dimensional Quality Assessment Framework" (ISO/IEC 25010)
  - 记忆维度: 节点丰富度+边连通性+银行利用率
  - 进化维度: 适应度+收敛奖励
  - 安全维度: 告警级别映射+失败惩罚
  - 效率维度: 运行时间+失败率
  - 一致性维度: 漂移惩罚+边节点比

算法:
    evaluate(node_count, edge_count, ...):
        1. 计算5个维度评分(0-1)
        2. 加权综合评分(w1=0.25, w2=0.25, w3=0.2, w4=0.15, w5=0.15)
        3. 根据综合评分映射等级(A+/A/A-...D/F)

来源: Omega系统 five_view 评估框架
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

from dataclasses import dataclass, field
from typing import Any


# ============================================================
# Sub-dimension dataclass for granular scoring
# ============================================================

@dataclass
class SubDimension:
    """A single sub-dimension score within a view."""
    name: str = ""
    score: float = 0.0
    weight: float = 1.0
    details: str = ""


@dataclass
class ViewScore:
    """Score for one of the 5 views, with granular sub-dimensions."""
    name: str = ""
    composite: float = 0.0
    sub_dimensions: list[SubDimension] = field(default_factory=list)


@dataclass
class ScoreProfile:
    """Full scoring profile with per-dimension scores, overall, and trend.

    Stores the current evaluation alongside optional previous data
    so callers can compute deltas.
    """
    composite_score: float = 0.0
    grade: str = "F"
    memory: ViewScore = field(default_factory=lambda: ViewScore(name="memory"))
    evolution: ViewScore = field(default_factory=lambda: ViewScore(name="evolution"))
    safety: ViewScore = field(default_factory=lambda: ViewScore(name="safety"))
    efficiency: ViewScore = field(default_factory=lambda: ViewScore(name="efficiency"))
    coherence: ViewScore = field(default_factory=lambda: ViewScore(name="coherence"))
    previous_composite: float | None = None
    previous_grade: str | None = None
    trend: str = "stable"  # "improving", "declining", "stable", "first"


@dataclass
class FiveViewReport:
    composite_score: float = 0.5
    grade: str = "B"
    views: dict = field(default_factory=dict)
    profile: ScoreProfile | None = None


class FiveViewEvaluator:
    """5-view evaluation: memory, evolution, safety, efficiency, coherence.

    Each view includes granular sub-dimensions. The evaluator supports
    trend tracking (compare current to previous) and improvement suggestions.

    Usage:
        evaluator = FiveViewEvaluator()
        report = evaluator.evaluate(
            node_count=100, edge_count=50, bank_count=80,
            evolution_fitness=0.7, alert_level="GREEN",
            uptime_s=3600, failure_count=2,
        )
        print(report.composite_score, report.grade)
    """

    GRADES = [
        (0.9, "A+"), (0.85, "A"), (0.8, "A-"),
        (0.75, "B+"), (0.7, "B"), (0.65, "B-"),
        (0.6, "C+"), (0.5, "C"), (0.4, "C-"),
        (0.3, "D"), (0.0, "F"),
    ]

    # Default weights for the 5 main dimensions
    DEFAULT_WEIGHTS = {
        "memory": 0.25,
        "evolution": 0.25,
        "safety": 0.20,
        "efficiency": 0.15,
        "coherence": 0.15,
    }

    def __init__(self, weights: dict[str, float] | None = None):
        self._weights = weights or dict(self.DEFAULT_WEIGHTS)
        self._reports: list[FiveViewReport] = []
        self._profiles: list[ScoreProfile] = []

    # ============================================================
    # Sub-dimension helpers
    # ============================================================

    @staticmethod
    def _memory_sub_scores(node_count: int, edge_count: int,
                           bank_count: int) -> list[SubDimension]:
        """Granular sub-dimensions for the memory view."""
        node_score = min(1.0, node_count / 1000)
        edge_ratio = min(1.0, edge_count / max(node_count, 1)) if node_count > 0 else 0.0
        bank_ratio = min(1.0, bank_count / max(node_count, 1)) if node_count > 0 else 0.0

        return [
            SubDimension(name="node_richness", score=node_score, weight=0.4,
                         details=f"{node_count} nodes / 1000 target"),
            SubDimension(name="edge_connectivity", score=edge_ratio, weight=0.3,
                         details=f"edge/node ratio: {edge_count}/{max(node_count,1)}"),
            SubDimension(name="bank_utilization", score=bank_ratio, weight=0.3,
                         details=f"bank/node ratio: {bank_count}/{max(node_count,1)}"),
        ]

    @staticmethod
    def _evolution_sub_scores(evolution_fitness: float,
                              convergence: bool) -> list[SubDimension]:
        """Granular sub-dimensions for the evolution view."""
        base_fitness = max(0.0, min(1.0, evolution_fitness))
        convergence_bonus = 0.1 if convergence else 0.0
        diversity_health = min(1.0, evolution_fitness * 1.2)  # proxy

        return [
            SubDimension(name="fitness", score=base_fitness, weight=0.5,
                         details=f"evolution_fitness={evolution_fitness:.3f}"),
            SubDimension(name="convergence_bonus", score=convergence_bonus, weight=0.2,
                         details=f"converged={'yes' if convergence else 'no'}"),
            SubDimension(name="diversity_health", score=diversity_health, weight=0.3,
                         details=f"proxy diversity={diversity_health:.3f}"),
        ]

    @staticmethod
    def _safety_sub_scores(alert_level: str,
                           failure_count: int) -> list[SubDimension]:
        """Granular sub-dimensions for the safety view."""
        safety_base = {"GREEN": 1.0, "YELLOW": 0.7,
                       "ORANGE": 0.4, "RED": 0.1}.get(alert_level, 0.5)
        failure_penalty = min(0.3, failure_count * 0.05)
        network_integrity = max(0.0, 1.0 - failure_penalty * 0.5)

        return [
            SubDimension(name="alert_status", score=safety_base, weight=0.4,
                         details=f"alert_level={alert_level} → {safety_base:.2f}"),
            SubDimension(name="failure_penalty", score=1.0 - failure_penalty, weight=0.3,
                         details=f"{failure_count} failures, penalty={failure_penalty:.2f}"),
            SubDimension(name="network_integrity", score=network_integrity, weight=0.3,
                         details=f"integrity={network_integrity:.3f}"),
        ]

    @staticmethod
    def _efficiency_sub_scores(uptime_s: float,
                               failure_count: int) -> list[SubDimension]:
        """Granular sub-dimensions for the efficiency view."""
        uptime_score = min(1.0, uptime_s / 86400)
        hours = max(uptime_s / 3600, 0.1)
        failure_rate = failure_count / hours
        efficiency_base = 1.0 - min(1.0, failure_rate)
        throughput = min(1.0, (1.0 / max(hours, 1)) * 3600)  # ops per simulated hour

        return [
            SubDimension(name="uptime", score=uptime_score, weight=0.3,
                         details=f"uptime={uptime_s:.0f}s / 86400 target"),
            SubDimension(name="failure_rate", score=efficiency_base, weight=0.4,
                         details=f"fail_rate={failure_rate:.4f} fails/hr"),
            SubDimension(name="throughput", score=throughput, weight=0.3,
                         details=f"throughput_score={throughput:.3f}"),
        ]

    @staticmethod
    def _coherence_sub_scores(node_count: int, edge_count: int,
                              drift_alerts: int) -> list[SubDimension]:
        """Granular sub-dimensions for the coherence view."""
        drift_penalty = min(0.5, drift_alerts * 0.1)
        edge_node_ratio = min(1.0, edge_count / max(node_count, 1)) if node_count > 0 else 0.5
        coherence_base = max(0.0, edge_node_ratio - drift_penalty)
        structural_balance = max(0.0, 1.0 - abs(edge_node_ratio - 0.5) * 2)

        return [
            SubDimension(name="drift_resilience", score=1.0 - drift_penalty, weight=0.35,
                         details=f"{drift_alerts} alerts, penalty={drift_penalty:.2f}"),
            SubDimension(name="edge_node_balance", score=edge_node_ratio, weight=0.35,
                         details=f"ratio={edge_node_ratio:.3f}"),
            SubDimension(name="structural_balance", score=structural_balance, weight=0.30,
                         details=f"balance={structural_balance:.3f}"),
        ]

    # ============================================================
    # Core evaluation
    # ============================================================

    def evaluate(self, node_count: int = 0, edge_count: int = 0,
                 bank_count: int = 0, evolution_fitness: float = 0.5,
                 alert_level: str = "GREEN", uptime_s: float = 0,
                 failure_count: int = 0, convergence: bool = False,
                 drift_alerts: int = 0) -> FiveViewReport:
        views: dict[str, float] = {}
        profile = ScoreProfile()

        # ---- Memory ----
        mem_subs = self._memory_sub_scores(node_count, edge_count, bank_count)
        mem_composite = sum(s.score * s.weight for s in mem_subs)
        views["memory"] = mem_composite
        profile.memory = ViewScore(name="memory", composite=mem_composite,
                                   sub_dimensions=mem_subs)

        # ---- Evolution ----
        evo_subs = self._evolution_sub_scores(evolution_fitness, convergence)
        evo_composite = sum(s.score * s.weight for s in evo_subs)
        views["evolution"] = min(1.0, evo_composite)
        profile.evolution = ViewScore(name="evolution", composite=views["evolution"],
                                      sub_dimensions=evo_subs)

        # ---- Safety ----
        saf_subs = self._safety_sub_scores(alert_level, failure_count)
        saf_composite = sum(s.score * s.weight for s in saf_subs)
        views["safety"] = max(0.0, saf_composite)
        profile.safety = ViewScore(name="safety", composite=views["safety"],
                                   sub_dimensions=saf_subs)

        # ---- Efficiency ----
        eff_subs = self._efficiency_sub_scores(uptime_s, failure_count)
        eff_composite = sum(s.score * s.weight for s in eff_subs)
        views["efficiency"] = max(0.0, eff_composite)
        profile.efficiency = ViewScore(name="efficiency", composite=views["efficiency"],
                                      sub_dimensions=eff_subs)

        # ---- Coherence ----
        coh_subs = self._coherence_sub_scores(node_count, edge_count, drift_alerts)
        coh_composite = sum(s.score * s.weight for s in coh_subs)
        views["coherence"] = max(0.0, coh_composite)
        profile.coherence = ViewScore(name="coherence", composite=views["coherence"],
                                      sub_dimensions=coh_subs)

        # Composite: weighted average
        composite = sum(views[k] * self._weights.get(k, 0.2) for k in views)
        composite = max(0.0, min(1.0, composite))

        # Grade
        grade = "F"
        for threshold, g in self.GRADES:
            if composite >= threshold:
                grade = g
                break

        # Trend tracking
        if self._profiles:
            prev = self._profiles[-1]
            diff = composite - prev.composite_score
            if diff > 0.02:
                trend = "improving"
            elif diff < -0.02:
                trend = "declining"
            else:
                trend = "stable"
            profile.previous_composite = prev.composite_score
            profile.previous_grade = prev.grade
        else:
            trend = "first"

        profile.composite_score = composite
        profile.grade = grade
        profile.trend = trend

        report = FiveViewReport(
            composite_score=composite,
            grade=grade,
            views=views,
            profile=profile,
        )
        self._reports.append(report)
        self._profiles.append(profile)
        return report

    # ============================================================
    # Improvement suggestions
    # ============================================================

    def get_improvement_suggestions(self, report: FiveViewReport | None = None) -> list[dict]:
        """Identify which dimensions need most improvement.

        Args:
            report: The report to analyze. If None, uses the latest.

        Returns:
            List of dicts, sorted by need (lowest score first), each with:
                - dimension: str
                - score: float
                - weight: float (impact on composite)
                - sub_dimensions: list of low-scoring sub-dimensions
                - suggestion: str
        """
        if report is None:
            if not self._reports:
                return []
            report = self._reports[-1]

        suggestions = []
        for dim_name in ["memory", "evolution", "safety", "efficiency", "coherence"]:
            dim_score = report.views.get(dim_name, 0.0)
            dim_weight = self._weights.get(dim_name, 0.2)
            impact = dim_score * dim_weight  # contribution to composite

            # Pull sub-dimension details from profile
            weak_subs: list[str] = []
            if report.profile:
                vs: ViewScore | None = getattr(report.profile, dim_name, None)
                if vs and vs.sub_dimensions:
                    for sd in vs.sub_dimensions:
                        if sd.score < 0.5:
                            weak_subs.append(f"{sd.name}={sd.score:.3f}")

            suggestions.append({
                "dimension": dim_name,
                "score": round(dim_score, 4),
                "weight": dim_weight,
                "impact": round(impact, 4),
                "weak_sub_dimensions": weak_subs,
                "suggestion": self._dimension_suggestion(dim_name, dim_score, weak_subs),
            })

        # Sort by score ascending (most needy first)
        suggestions.sort(key=lambda x: x["score"])
        return suggestions

    @staticmethod
    def _dimension_suggestion(dim: str, score: float,
                              weak_subs: list[str]) -> str:
        """Generate human-readable improvement suggestion."""
        if score >= 0.8:
            return f"{dim}: Good — maintain current levels."
        if score >= 0.6:
            return f"{dim}: Moderate — minor improvements recommended."
        if weak_subs:
            subs = ", ".join(weak_subs)
            return f"{dim}: Needs improvement (score={score:.2f}). Focus on: {subs}."
        return f"{dim}: Needs significant improvement (score={score:.2f})."

    # ============================================================
    # Trend analysis
    # ============================================================

    def get_trend(self, report: FiveViewReport | None = None) -> dict:
        """Compare current evaluation to previous.

        Args:
            report: The current report. If None, uses the latest.

        Returns:
            dict with trend info per dimension and overall.
        """
        if report is None:
            if not self._reports:
                return {"overall_trend": "no_data"}
            report = self._reports[-1]

        # Find the previous report
        idx = self._reports.index(report) if report in self._reports else -1
        if idx <= 0:
            return {"overall_trend": "first_evaluation"}

        prev = self._reports[idx - 1]

        # Per-dimension deltas
        dims: dict[str, dict[str, float]] = {}
        for dim in ["memory", "evolution", "safety", "efficiency", "coherence"]:
            cur = report.views.get(dim, 0.0)
            prv = prev.views.get(dim, 0.0)
            dims[dim] = {
                "current": round(cur, 4),
                "previous": round(prv, 4),
                "delta": round(cur - prv, 4),
            }

        overall_delta = report.composite_score - prev.composite_score
        if overall_delta > 0.02:
            trend_label = "improving"
        elif overall_delta < -0.02:
            trend_label = "declining"
        else:
            trend_label = "stable"

        return {
            "overall_trend": trend_label,
            "overall_delta": round(overall_delta, 4),
            "current_composite": round(report.composite_score, 4),
            "previous_composite": round(prev.composite_score, 4),
            "current_grade": report.grade,
            "previous_grade": prev.grade,
            "dimensions": dims,
        }

    # ============================================================
    # Standard helpers
    # ============================================================

    def get_stats(self) -> dict:
        scores = [r.composite_score for r in self._reports]
        return {
            "reports": len(self._reports),
            "avg_score": sum(scores) / max(len(scores), 1),
            "last_score": scores[-1] if scores else 0,
            "last_grade": self._reports[-1].grade if self._reports else "N/A",
            "trend": self._profiles[-1].trend if self._profiles else "none",
        }
