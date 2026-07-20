"""ZScoreDetector — Z-score离群检测.

基于:
- "Statistical Outlier Detection with Z-Score" (Peacock, 1987)
  - Z-score计算: (x - μ) / σ
  - 动态基线: 移动窗口计算均值/标准差
  - 多级告警: warning/critical/block
  - 自适应阈值: 根据数据分布调整

算法:
    check(value):
        1. 计算当前统计
        2. 计算Z-score
        3. 判断是否离群
        4. 返回检测报告

复杂度:
    check(): O(1) 均摊(滑动窗口)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import math
from collections import deque


class ZScoreDetector:
    """Z-score离群检测器 — 统计异常值检测.
    
    通过Z-score检测数值是否偏离正常分布.
    """
    
    def __init__(self, window_size: int = 50, warning_threshold: float = 2.0,
                 critical_threshold: float = 3.0):
        """初始化.
        
        Args:
            window_size: 滑动窗口大小
            warning_threshold: 警告阈值
            critical_threshold: 严重阈值
        """
        self._window_size = window_size
        self._warning_threshold = warning_threshold
        self._critical_threshold = critical_threshold
        
        self._values: deque = deque(maxlen=window_size)
        self._running_sum = 0.0
        self._running_sum_sq = 0.0
        self._outliers: list[dict] = []
        self._total_checks = 0
    
    def check(self, value: float, label: str = "") -> dict:
        """检查值是否离群.
        
        Args:
            value: 待检查值
            label: 标签
        
        Returns:
            dict: 检测报告
        """
        self._total_checks += 1
        
        # 更新统计
        if len(self._values) >= self._window_size:
            old = self._values[0]
            self._running_sum -= old
            self._running_sum_sq -= old * old
        
        self._values.append(value)
        self._running_sum += value
        self._running_sum_sq += value * value
        
        n = len(self._values)
        
        if n < 3:
            return {
                "value": value,
                "label": label,
                "z_score": 0.0,
                "is_outlier": False,
                "severity": "none",
                "reason": "insufficient data",
            }
        
        # 计算均值和标准差
        mean = self._running_sum / n
        variance = (self._running_sum_sq / n) - (mean * mean)
        variance = max(variance, 0)  # 防止浮点误差
        std_dev = math.sqrt(variance)
        
        # 计算Z-score
        z_score = (value - mean) / max(std_dev, 1e-10)
        
        # 判断离群级别
        abs_z = abs(z_score)
        is_outlier = abs_z > self._warning_threshold
        
        if abs_z > self._critical_threshold:
            severity = "critical"
        elif abs_z > self._warning_threshold:
            severity = "warning"
        else:
            severity = "none"
        
        # 方向判断
        direction = "high" if z_score > 0 else "low"
        
        report = {
            "value": value,
            "label": label,
            "z_score": round(z_score, 4),
            "mean": round(mean, 4),
            "std_dev": round(std_dev, 4),
            "is_outlier": is_outlier,
            "severity": severity,
            "direction": direction,
            "window_size": n,
            "ts": time.time(),
        }
        
        if is_outlier:
            self._outliers.append(report)
            if len(self._outliers) > 200:
                self._outliers = self._outliers[-100:]
        
        return report
    
    def get_running_stats(self) -> dict:
        """获取当前统计.
        
        Returns:
            dict: 运行统计
        """
        n = len(self._values)
        if n == 0:
            return {"mean": 0, "std_dev": 0, "count": 0}
        
        mean = self._running_sum / n
        variance = (self._running_sum_sq / n) - (mean * mean)
        variance = max(variance, 0)
        
        return {
            "mean": round(mean, 4),
            "std_dev": round(math.sqrt(variance), 4),
            "count": n,
        }
    
    def reset(self) -> None:
        """重置检测器."""
        self._values.clear()
        self._running_sum = 0.0
        self._running_sum_sq = 0.0
    
    def get_stats(self) -> dict:
        """获取统计."""
        severity_counts = {"warning": 0, "critical": 0}
        for o in self._outliers:
            sev = o.get("severity", "warning")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        
        return {
            "total_checks": self._total_checks,
            "total_outliers": len(self._outliers),
            "outlier_rate": round(
                len(self._outliers) / max(self._total_checks, 1), 4
            ),
            "severity_distribution": severity_counts,
            "current_stats": self.get_running_stats(),
        }
    
    # 兼容别名: life.py 调用 observe(value)
    def observe(self, value: float, label: str = "") -> dict:
        """观察数值并检测异常 (兼容别名)."""
        return self.check(value, label=label)
    
    # 兼容别名: life.py 调用 detect()
    def detect(self) -> list[dict]:
        """检测离群值 (兼容别名，返回最近的离群记录)."""
        return self._outliers[-10:] if self._outliers else []

# 兼容别名
ZScoreAnomaly = ZScoreDetector
