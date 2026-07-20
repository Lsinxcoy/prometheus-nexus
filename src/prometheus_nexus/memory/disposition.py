"""DispositionLearner — Behavioral disposition learning from value patterns.

基于:
- "Online Change Detection with CUSUM" (Page, 1954) + Omega行为倾向学习
  - 运行统计: Welford算法计算均值/方差
  - 偏移检测: |new_mean - old_mean| > threshold → CUSUM-like
  - 趋势预测: 线性回归(slope)预测下一个值
  - 波动性分析: 方差排序找出最不稳定/最稳定模式

算法:
    learn(pattern_key, value):
        1. 追加值到历史(上限max_values)
        2. 计算新均值(运行统计)
        3. 检测偏移: |new_mean - old_mean| > threshold

    predict(pattern_key):
        1. 线性回归计算slope
        2. prediction = last_value + slope
        3. confidence = min(1.0, n/20)

来源: Omega系统 disposition 行为倾向学习模块 + MiMo模式追踪
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import math
import time
from collections import defaultdict


class DispositionLearner:
    """Behavioral disposition learning.

    Usage:
        learner = DispositionLearner()
        learner.learn("response_quality", 0.8)
        learner.learn("response_quality", 0.9)
        learner.learn("response_quality", 0.3)  # shift!

        disp = learner.get_disposition("response_quality")
        shifts = learner.detect_shifts("response_quality")
    """

    def __init__(self, max_values: int = 100, shift_threshold: float = 0.1):
        """Initialize the disposition learner.

        Args:
            max_values: Maximum values to track per pattern.
            shift_threshold: Threshold for detecting disposition shifts.
        """
        self._max_values = max_values
        self._shift_threshold = shift_threshold
        self._values: dict[str, list[float]] = defaultdict(list)
        self._means: dict[str, float] = {}
        self._variances: dict[str, float] = {}
        self._shifts: dict[str, int] = defaultdict(int)
        self._shift_history: dict[str, list[dict]] = defaultdict(list)

    def learn(self, pattern_key: str, value: float) -> None:
        """Record a value for a behavioral pattern.

        Args:
            pattern_key: Pattern identifier (e.g., "response_quality").
            value: Observed value [0, 1].
        """
        values = self._values[pattern_key]
        old_mean = self._means.get(pattern_key, value)

        values.append(value)
        if len(values) > self._max_values:
            values[:] = values[-self._max_values // 2:]

        # Update running statistics
        new_mean = sum(values) / len(values)
        self._means[pattern_key] = new_mean

        if len(values) >= 2:
            variance = sum((v - new_mean) ** 2 for v in values) / len(values)
            self._variances[pattern_key] = variance

        # Detect shift
        if abs(new_mean - old_mean) > self._shift_threshold:
            self._shifts[pattern_key] += 1
            self._shift_history[pattern_key].append({
                "old_mean": old_mean,
                "new_mean": new_mean,
                "delta": new_mean - old_mean,
                "timestamp": time.time(),
            })

    def get_disposition(self, pattern_key: str) -> float:
        """Get current mean disposition for a pattern."""
        return self._means.get(pattern_key, 0.5)

    def get_variance(self, pattern_key: str) -> float:
        """Get variance of values for a pattern."""
        return self._variances.get(pattern_key, 0.0)

    def get_std(self, pattern_key: str) -> float:
        """Get standard deviation for a pattern."""
        return math.sqrt(self._variances.get(pattern_key, 0.0))

    def get_shift_count(self, pattern_key: str) -> int:
        """Get number of disposition shifts detected."""
        return self._shifts.get(pattern_key, 0)

    def get_shift_history(self, pattern_key: str) -> list[dict]:
        """Get shift history for a pattern."""
        return self._shift_history.get(pattern_key, [])

    def detect_shifts(self, pattern_key: str) -> list[dict]:
        """Detect all shifts for a pattern."""
        return self._shift_history.get(pattern_key, [])

    def get_all_dispositions(self) -> dict[str, float]:
        """Get dispositions for all patterns."""
        return dict(self._means)

    def get_most_volatile(self, top_k: int = 5) -> list[dict]:
        """Get patterns with highest variance (most volatile)."""
        ranked = sorted(self._variances.items(), key=lambda x: x[1], reverse=True)
        return [{"pattern": k, "variance": v, "std": math.sqrt(v)}
                for k, v in ranked[:top_k]]

    def get_most_stable(self, top_k: int = 5) -> list[dict]:
        """Get patterns with lowest variance (most stable)."""
        ranked = sorted(self._variances.items(), key=lambda x: x[1])
        return [{"pattern": k, "variance": v, "std": math.sqrt(v)}
                for k, v in ranked[:top_k]]

    def predict(self, pattern_key: str) -> dict:
        """Predict next value based on disposition and trend."""
        values = self._values.get(pattern_key, [])
        if len(values) < 2:
            return {"prediction": self.get_disposition(pattern_key), "confidence": 0.3}

        # Simple linear trend
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        den = sum((i - x_mean) ** 2 for i in range(n))
        slope = num / den if den != 0 else 0

        prediction = values[-1] + slope
        confidence = min(1.0, n / 20)  # More data = more confidence

        return {"prediction": max(0.0, min(1.0, prediction)), "confidence": confidence,
                "trend": "increasing" if slope > 0.01 else "decreasing" if slope < -0.01 else "stable"}

    def get_stats(self) -> dict:
        total_values = sum(len(v) for v in self._values.values())
        return {
            "patterns": len(self._values),
            "total_values": total_values,
            "total_shifts": sum(self._shifts.values()),
            "avg_variance": sum(self._variances.values()) / max(len(self._variances), 1),
        }
