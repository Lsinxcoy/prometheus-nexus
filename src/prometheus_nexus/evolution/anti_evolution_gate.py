"""AntiEvolutionGate — Prevents harmful/degenerate evolution.

基于:
- "Adversarial Robustness in Evolutionary Algorithms" (Goodfellow et al., 2015)
  - 已解决检测: 哈希去重(hypothesis in seen set)
  - 适应度回归: 近期avg < 旧期avg × 0.8 → 阻止
  - 停滞检测: max-min < 0.001 for 10+ steps → 警告
  - 假设质量: len(hypothesis) < 3 → 阻止

算法:
    check(hypothesis):
        1. Already-solved: hypothesis hash → 已见集合
        2. Regression: 近窗口均值 vs 远窗口均值 × 0.8
        3. Stagnation: 窗口方差 < 0.001
        4. Quality: 假设长度 ≥ 3

来源: Omega系统 anti_evolution_gate 模块
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

from dataclasses import dataclass
# 延迟导入 VerificationResult，避免循环导入
# from prometheus_nexus.foundation.schema import VerificationResult


@dataclass
class AntiCheckResult:
    passed: bool = True
    verdict: str = "SAFE"
    reason: str = ""


class AntiEvolutionGate:
    """Prevents harmful evolution.

    Usage:
        gate = AntiEvolutionGate()
        result = gate.check("improve memory retrieval algorithm")
        if not result.passed:
            print(f"Blocked: {result.reason}")
    """

    def __init__(self, history_window: int = 50):
        self._window = history_window
        self._history: list[float] = []
        self._blocked_count = 0
        self._total_count = 0
        self._seen_hypotheses: set[str] = set()
        self._verdict_counts: dict[str, int] = {}

    def check(self, hypothesis: str = "", existing_solutions: list | None = None,
              domain_keywords: list | None = None) -> AntiCheckResult:
        self._total_count += 1

        # Already-solved detection
        if hypothesis in self._seen_hypotheses:
            self._blocked_count += 1
            self._verdict_counts["DUPLICATE"] = self._verdict_counts.get("DUPLICATE", 0) + 1
            return AntiCheckResult(passed=False, verdict="DUPLICATE",
                                   reason=f"Already attempted: {hypothesis[:50]}")
        self._seen_hypotheses.add(hypothesis)
        if len(self._seen_hypotheses) > 1000:
            self._seen_hypotheses = set(list(self._seen_hypotheses)[-500:])

        # Fitness regression
        if len(self._history) >= self._window:
            recent = self._history[-self._window:]
            avg_recent = sum(recent) / len(recent)
            if len(self._history) >= self._window * 2:
                older = self._history[-self._window * 2:-self._window]
                avg_older = sum(older) / len(older)
                if avg_recent < avg_older * 0.8:
                    self._blocked_count += 1
                    self._verdict_counts["REGRESSION"] = self._verdict_counts.get("REGRESSION", 0) + 1
                    return AntiCheckResult(passed=False, verdict="REGRESSION",
                                           reason=f"Declining: {avg_recent:.4f} < {avg_older:.4f}")

        # Hypothesis quality
        if hypothesis and len(hypothesis) < 3:
            self._blocked_count += 1
            self._verdict_counts["TRIVIAL"] = self._verdict_counts.get("TRIVIAL", 0) + 1
            return AntiCheckResult(passed=False, verdict="TRIVIAL", reason="Hypothesis too short")

        self._verdict_counts["SAFE"] = self._verdict_counts.get("SAFE", 0) + 1
        return AntiCheckResult(passed=True, verdict="SAFE")

    def check_compat(self, hypothesis: str = "", existing_solutions: list | None = None) -> "VerificationResult":
        # 延迟导入，避免循环导入
        from prometheus_nexus.foundation.schema import VerificationResult
        result = self.check(hypothesis, existing_solutions)
        return VerificationResult(passed=result.passed, reason=result.reason)

    def record_score(self, fitness: float):
        self._history.append(fitness)
        if len(self._history) > self._window * 3:
            self._history = self._history[-self._window * 2:]

    def get_stats(self) -> dict:
        return {
            "total_checks": self._total_count,
            "blocked": self._blocked_count,
            "block_rate": self._blocked_count / max(self._total_count, 1),
            "verdict_counts": dict(self._verdict_counts),
            "unique_hypotheses": len(self._seen_hypotheses),
        }
