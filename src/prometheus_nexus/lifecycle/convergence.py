"""ConvergenceDetector — 收敛检测与停滞判断.

基于:
- "Statistical Convergence Detection in Evolutionary Algorithms"
  - 移动平均: 检测指标趋势
  - 方差检测: 低方差=收敛
  - 停滞检测: 连续无改进轮次
  - 重启建议: 检测到停滞时建议重置

算法:
    check(values):
        1. 计算移动平均趋势
        2. 检测方差变化
        3. 判断是否收敛/停滞
        4. 返回检测报告

复杂度:
    check(): O(N) N=窗口大小
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import math
from collections import deque


class ConvergenceDetector:
    """收敛检测器 — 统计检验判断算法收敛状态.
    
    通过移动平均和方差分析检测进化过程是否收敛或停滞.
    """
    
    def __init__(self, window_size: int = 20, staleness_threshold: int = 10,
                 variance_threshold: float = 0.01):
        """初始化.
        
        Args:
            window_size: 移动平均窗口
            staleness_threshold: 停滞阈值(连续无改进轮次)
            variance_threshold: 方差阈值
        """
        self._window_size = window_size
        self._staleness_threshold = staleness_threshold
        self._variance_threshold = variance_threshold
        
        self._history: deque = deque(maxlen=window_size * 2)
        self._best_value = float('-inf')
        self._no_improve_count = 0
        self._detections: list[dict] = []
    
    def record(self, value: float) -> None:
        """记录指标值.
        
        Args:
            value: 指标值
        """
        self._history.append(value)
        
        if value > self._best_value:
            self._best_value = value
            self._no_improve_count = 0
        else:
            self._no_improve_count += 1
    
    # 兼容别名: life.py 调用 observe / update
    def observe(self, value: float) -> None:
        """观察指标值 (兼容别名)."""
        self.record(value)
    
    def update(self, value: int | float) -> None:
        """更新指标值 (兼容别名)."""
        self.record(float(value))
    
    def check(self) -> dict:
        """检查收敛状态.
        
        Returns:
            dict: 检测报告
        """
        if len(self._history) < self._window_size:
            return {
                "converged": False,
                "stagnant": False,
                "reason": "insufficient data",
                "data_points": len(self._history),
            }
        
        values = list(self._history)
        
        # 1. 移动平均趋势
        window = values[-self._window_size:]
        mean = sum(window) / len(window)
        
        # 前后半窗口比较
        half = len(window) // 2
        first_half_mean = sum(window[:half]) / half
        second_half_mean = sum(window[half:]) / half
        trend = second_half_mean - first_half_mean
        
        # 2. 方差检测
        variance = sum((v - mean) ** 2 for v in window) / len(window)
        std_dev = math.sqrt(variance)
        
        # 3. 收敛判断
        converged = variance < self._variance_threshold and abs(trend) < 0.001
        stagnant = self._no_improve_count >= self._staleness_threshold
        
        # 4. 改进建议
        suggestion = None
        if stagnant and not converged:
            suggestion = "restart"
        elif converged:
            suggestion = "terminate"
        
        report = {
            "converged": converged,
            "stagnant": stagnant,
            "mean": round(mean, 6),
            "variance": round(variance, 6),
            "std_dev": round(std_dev, 6),
            "trend": round(trend, 6),
            "no_improve_count": self._no_improve_count,
            "best_value": round(self._best_value, 6),
            "suggestion": suggestion,
            "data_points": len(values),
            "ts": time.time(),
        }
        
        self._detections.append(report)
        if len(self._detections) > 200:
            self._detections = self._detections[-100:]
        
        return report
    
    def reset(self) -> None:
        """重置检测器."""
        self._history.clear()
        self._best_value = float('-inf')
        self._no_improve_count = 0
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "data_points": len(self._history),
            "best_value": round(self._best_value, 6),
            "detections": len(self._detections),
            "converged_count": sum(1 for d in self._detections if d.get("converged")),
            "stagnant_count": sum(1 for d in self._detections if d.get("stagnant")),
        }
    
    # 兼容别名: life.py 调用 is_converged / get_history
    def is_converged(self) -> bool:
        """检查是否收敛."""
        report = self.check()
        return report.get("converged", False)
    
    def get_history(self) -> list:
        """获取历史记录."""
        return list(self._history)
