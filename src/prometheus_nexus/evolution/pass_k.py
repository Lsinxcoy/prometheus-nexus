"""PassKConsistency — Pass-k consistency verification.

Based on: Legacy Omega pass_k.py + pass_k_consistency.py
Implements pass@k evaluation: sample k independent attempts,
calculate the probability that at least one passes.

Key Concepts:
    1. Pass@k = 1 - C(n-f, k) / C(n, k)
       where n = total samples, f = passing samples
    2. Multiple independent attempts per task
    3. Consensus threshold for acceptance
    4. Statistical confidence bounds

Algorithm:
    for each task:
        results = [evaluate(attempt) for attempt in range(k)]
        passing = sum(results)
        pass_at_k = 1 - comb(n-f, k) / comb(n, k)
        if pass_at_k >= threshold: ACCEPT
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class PassKAttempt:
    """A single attempt result."""
    attempt_id: int = 0
    output: str = ""
    passed: bool = False
    score: float = 0.0
    latency_ms: float = 0.0
    timestamp: float = 0.0


@dataclass
class PassKResult:
    """Result of pass@k evaluation."""
    task: str = ""
    k: int = 0
    n: int = 0  # total samples
    passing: int = 0
    pass_at_k: float = 0.0
    confidence_lower: float = 0.0
    confidence_upper: float = 0.0
    attempts: List[PassKAttempt] = field(default_factory=list)
    consensus: bool = False
    consensus_threshold: float = 0.0
    duration_ms: float = 0.0


class PassKConsistency:
    """Pass-k consistency verification engine.

    Implements statistical pass@k evaluation with confidence intervals
    and consensus verification. Based on legacy Omega implementation.

    Usage:
        pk = PassKConsistency(default_k=10, threshold=0.5)
        result = pk.evaluate(task="solve", evaluate_fn=my_evaluator)
        print(f"Pass@{result.k} = {result.pass_at_k:.3f}")
        print(f"Consensus: {result.consensus}")
    """

    def __init__(self, default_k: int = 10, threshold: float = 0.5,
                 confidence_level: float = 0.95, max_k: int = 100):
        """Initialize pass@k consistency checker.

        Args:
            default_k: Default number of samples for pass@k.
            threshold: Minimum pass@k for acceptance.
            confidence_level: Confidence level for statistical bounds.
            max_k: Maximum allowed k value.
        """
        self._default_k = default_k
        self._threshold = threshold
        self._confidence_level = confidence_level
        self._max_k = max_k
        self._history: List[PassKResult] = []
        self._task_stats: Dict[str, Dict[str, Any]] = {}

    def evaluate(self, task: str, evaluate_fn: Optional[Callable] = None,
                 k: Optional[int] = None, threshold: Optional[float] = None,
                 max_attempts: int = 100) -> PassKResult:
        """Run pass@k evaluation for a task.

        Args:
            task: Task description.
            evaluate_fn: Function that returns (passed: bool, score: float).
            k: Number of samples (pass@k).
            threshold: Acceptance threshold.
            max_attempts: Maximum attempts before timeout.

        Returns:
            PassKResult with pass@k score and confidence bounds.
        """
        k = min(k or self._default_k, self._max_k)
        threshold = threshold or self._threshold
        start = time.time()

        if not evaluate_fn:
            return self._default_evaluation(task, k, threshold, start)

        # Run k independent attempts
        attempts = []
        for i in range(k):
            passed, score = self._run_attempt(evaluate_fn, task, i)
            attempt = PassKAttempt(
                attempt_id=i,
                output=f"attempt_{i}",
                passed=passed,
                score=score,
                timestamp=time.time(),
            )
            attempts.append(attempt)

            # Early exit if consensus reached
            if len(attempts) >= 3:
                current_passing = sum(1 for a in attempts if a.passed)
                current_rate = current_passing / len(attempts)
                if current_rate >= min(0.9, threshold + 0.2):
                    break

        passing = sum(1 for a in attempts if a.passed)
        n = len(attempts)

        # Calculate pass@k
        pass_at_k = self._calculate_pass_at_k(n, passing, k)

        # Confidence bounds (Wilson score interval)
        conf_lower, conf_upper = self._wilson_interval(passing, n, self._confidence_level)

        # Consensus check
        consensus = passing / max(n, 1) >= threshold

        duration_ms = (time.time() - start) * 1000

        result = PassKResult(
            task=task,
            k=k,
            n=n,
            passing=passing,
            pass_at_k=pass_at_k,
            confidence_lower=conf_lower,
            confidence_upper=conf_upper,
            attempts=attempts,
            consensus=consensus,
            consensus_threshold=threshold,
            duration_ms=duration_ms,
        )

        self._history.append(result)
        self._update_task_stats(task, result)

        return result

    def _run_attempt(self, evaluate_fn: Callable, task: str, attempt_id: int) -> tuple:
        """Run a single evaluation attempt.

        Returns:
            (passed: bool, score: float)
        """
        try:
            result = evaluate_fn(task, attempt_id)
            if isinstance(result, tuple):
                passed, score = result
            elif isinstance(result, dict):
                passed = result.get("passed", result.get("success", False))
                score = result.get("score", 0.0)
            else:
                score = float(result)
                passed = score >= 0.5
            return bool(passed), float(score)
        except Exception:
            logger.warning("PassK: evaluation failed, returning 0")
            return False, 0.0

    def _default_evaluation(self, task: str, k: int, threshold: float,
                            start: float) -> PassKResult:
        """Default evaluation when no function provided."""
        attempts = []
        passing = 0

        for i in range(k):
            # Simulate evaluation with task-dependent scoring
            score = self._heuristic_score(task, i)
            passed = score >= threshold
            if passed:
                passing += 1
            attempts.append(PassKAttempt(
                attempt_id=i, passed=passed, score=score, timestamp=time.time(),
            ))

        pass_at_k = self._calculate_pass_at_k(k, passing, k)
        conf_lower, conf_upper = self._wilson_interval(passing, k, self._confidence_level)

        return PassKResult(
            task=task, k=k, n=k, passing=passing,
            pass_at_k=pass_at_k, confidence_lower=conf_lower,
            confidence_upper=conf_upper, attempts=attempts,
            consensus=passing / k >= threshold,
            consensus_threshold=threshold,
            duration_ms=(time.time() - start) * 1000,
        )

    def _heuristic_score(self, task: str, attempt_id: int) -> float:
        """Heuristic scoring based on task characteristics."""
        base = 0.5
        task_lower = task.lower()

        # Task complexity affects base score
        if any(w in task_lower for w in ["debug", "fix", "error"]):
            base += 0.1
        if any(w in task_lower for w in ["create", "design", "build"]):
            base -= 0.05

        # Attempt variance
        variance = random.gauss(0, 0.15)
        return max(0.0, min(1.0, base + variance))

    def _calculate_pass_at_k(self, n: int, passing: int, k: int) -> float:
        """Calculate pass@k: P(at least 1 pass in k samples).

        pass@k = 1 - C(n-f, k) / C(n, k)
        where f = number of passing samples
        """
        if n == 0:
            return 0.0
        if passing >= k:
            return 1.0
        if passing == 0:
            return 0.0

        failing = n - passing
        if failing >= k:
            # Use log-space to avoid overflow
            log_comb_nf_k = self._log_comb(failing, k)
            log_comb_n_k = self._log_comb(n, k)
            ratio = math.exp(log_comb_nf_k - log_comb_n_k)
            return 1.0 - ratio
        return 1.0

    def _log_comb(self, n: int, k: int) -> float:
        """Log-space combination: log(C(n, k))."""
        if k < 0 or k > n:
            return float('-inf')
        if k == 0 or k == n:
            return 0.0
        if k > n // 2:
            k = n - k
        # log(n!) - log(k!) - log((n-k)!)
        return (self._log_factorial(n) - self._log_factorial(k)
                - self._log_factorial(n - k))

    @staticmethod
    def _log_factorial(n: int) -> float:
        """Log-factorial using lgamma."""
        return math.lgamma(n + 1)

    def _wilson_interval(self, successes: int, n: int,
                         confidence: float = 0.95) -> tuple:
        """Wilson score confidence interval for binomial proportion.

        Returns (lower, upper) bounds.
        """
        if n == 0:
            return (0.0, 1.0)

        p = successes / n
        z = self._norm_ppf((1 + confidence) / 2)

        denominator = 1 + z ** 2 / n
        centre = (p + z ** 2 / (2 * n)) / denominator
        margin = z * math.sqrt((p * (1 - p) + z ** 2 / (4 * n)) / n) / denominator

        return (max(0.0, centre - margin), min(1.0, centre + margin))

    @staticmethod
    def _norm_ppf(p: float) -> float:
        """Approximate inverse normal CDF (percent point function).

        Uses rational approximation (Abramowitz & Stegun).
        """
        if p <= 0:
            return float('-inf')
        if p >= 1:
            return float('inf')
        if p == 0.5:
            return 0.0

        # For p < 0.5, use symmetry
        if p > 0.5:
            return -PassKConsistency._norm_ppf(1 - p)

        # Rational approximation for p in (0, 0.5]
        t = math.sqrt(-2.0 * math.log(p))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        return -(t - (c0 + c1 * t + c2 * t ** 2) /
                 (1 + d1 * t + d2 * t ** 2 + d3 * t ** 3))

    def verify_consensus(self, task: str, outputs: List[str],
                         evaluate_fn: Optional[Callable] = None,
                         threshold: Optional[float] = None) -> Dict[str, Any]:
        """Verify if multiple outputs reach consensus.

        Args:
            task: Task description.
            outputs: List of candidate outputs.
            evaluate_fn: Evaluation function.
            threshold: Consensus threshold.

        Returns:
            Dict with consensus status and details.
        """
        threshold = threshold or self._threshold
        k = len(outputs)

        if k == 0:
            return {"consensus": False, "reason": "no_outputs", "k": 0}

        # Score each output
        scores = []
        for i, output in enumerate(outputs):
            if evaluate_fn:
                try:
                    result = evaluate_fn(task, output)
                    score = result if isinstance(result, (int, float)) else 0.5
                except Exception:
                    logger.warning("PassK: evaluate_fn raised, scoring 0.0")
                    score = 0.0
            else:
                score = self._heuristic_score(output, i)
            scores.append(score)

        passing = sum(1 for s in scores if s >= threshold)
        pass_rate = passing / k

        # Check for clustering (consensus = high agreement)
        mean_score = sum(scores) / k
        variance = sum((s - mean_score) ** 2 for s in scores) / k

        return {
            "consensus": pass_rate >= threshold,
            "pass_rate": pass_rate,
            "mean_score": mean_score,
            "variance": variance,
            "k": k,
            "passing": passing,
            "scores": scores,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get pass@k statistics."""
        if not self._history:
            return {"evaluations": 0}

        all_pass_at_k = [r.pass_at_k for r in self._history]
        return {
            "evaluations": len(self._history),
            "avg_pass_at_k": sum(all_pass_at_k) / len(all_pass_at_k),
            "best_pass_at_k": max(all_pass_at_k),
            "consensus_rate": sum(1 for r in self._history if r.consensus) / len(self._history),
            "total_attempts": sum(r.n for r in self._history),
            "task_stats": dict(list(self._task_stats.items())[:10]),
        }

    def _update_task_stats(self, task: str, result: PassKResult) -> None:
        """Update running statistics for a task."""
        if task not in self._task_stats:
            self._task_stats[task] = {
                "evaluations": 0,
                "total_passing": 0,
                "total_samples": 0,
                "avg_pass_at_k": 0.0,
            }
        stats = self._task_stats[task]
        stats["evaluations"] += 1
        stats["total_passing"] += result.passing
        stats["total_samples"] += result.n
        # Running average
        n = stats["evaluations"]
        stats["avg_pass_at_k"] = (
            (stats["avg_pass_at_k"] * (n - 1) + result.pass_at_k) / n
        )
