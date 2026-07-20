"""TrendDetector — 趋势检测与预测.

基于:
- "Exponential Smoothing for Time Series Forecasting" (Holt & Winter, 1957)
  - 指数平滑: 近期数据权重更高
  - 趋势检测: 上升/下降/平稳
  - 季节性分解: 分离趋势和周期
  - 预测: 基于趋势外推

算法:
    smooth(values, alpha):
        1. 指数平滑
        2. 计算平滑序列
    
    detect_trend(values):
        1. 计算平滑序列
        2. 线性回归斜率
        3. 判断趋势方向

复杂度:
    smooth(): O(N)
    detect_trend(): O(N)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import math
from collections import deque


class TrendDetector:
    """趋势检测器 — 指数平滑+线性回归趋势分析.
    
    检测时间序列数据的趋势方向和强度.
    """
    
    def __init__(self, window_size: int = 20, alpha: float = 0.3):
        """初始化.
        
        Args:
            window_size: 窗口大小
            alpha: 平滑因子 [0, 1]
        """
        self._window_size = window_size
        self._alpha = alpha
        self._history: deque = deque(maxlen=window_size * 2)
        self._smoothed: deque = deque(maxlen=window_size * 2)
        self._trend_log: list[dict] = []
    
    def record(self, value: float) -> None:
        """记录数据点.
        
        Args:
            value: 数据值
        """
        self._history.append(value)
        
        # 指数平滑
        if len(self._history) == 1:
            self._smoothed.append(value)
        else:
            prev = self._smoothed[-1]
            smoothed = self._alpha * value + (1 - self._alpha) * prev
            self._smoothed.append(smoothed)
    
    def detect_trend(self) -> dict:
        """检测趋势.
        
        Returns:
            dict: 趋势报告
        """
        if len(self._history) < 5:
            return {
                "trend": "insufficient_data",
                "direction": "unknown",
                "strength": 0.0,
            }
        
        values = list(self._history)
        smoothed = list(self._smoothed)
        
        # 1. 线性回归
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        slope = numerator / max(denominator, 1e-10)
        
        # 2. 相关系数
        y_std = math.sqrt(sum((v - y_mean) ** 2 for v in values) / max(n, 1))
        x_std = math.sqrt(denominator / max(n, 1))
        correlation = numerator / max(n * x_std * y_std, 1e-10)
        
        # 3. 趋势判断
        if abs(correlation) < 0.3:
            direction = "flat"
            strength = 0.0
        elif correlation > 0:
            direction = "rising"
            strength = correlation
        else:
            direction = "falling"
            strength = abs(correlation)
        
        # 4. 加速度(趋势变化率)
        acceleration = 0.0
        if len(smoothed) >= 6:
            half = len(smoothed) // 2
            first_slope = (smoothed[half] - smoothed[0]) / half
            second_slope = (smoothed[-1] - smoothed[half]) / half
            acceleration = second_slope - first_slope
        
        report = {
            "trend": direction,
            "direction": direction,
            "strength": round(strength, 4),
            "slope": round(slope, 6),
            "correlation": round(correlation, 4),
            "acceleration": round(acceleration, 6),
            "current_value": values[-1],
            "mean": round(y_mean, 4),
            "data_points": n,
            "ts": time.time(),
        }
        
        self._trend_log.append(report)
        if len(self._trend_log) > 200:
            self._trend_log = self._trend_log[-100:]
        
        return report
    
    def predict(self, steps: int = 1) -> float:
        """预测未来值.
        
        Args:
            steps: 预测步数
        
        Returns:
            float: 预测值
        """
        if len(self._history) < 3:
            return 0.0
        
        trend = self.detect_trend()
        current = self._history[-1]
        slope = trend.get("slope", 0)
        
        return current + slope * steps
    
    # 兼容别名: life.py 调用 observe(series, value)
    def observe(self, series: str, value: float) -> dict:
        """观察数值并记录趋势 (兼容别名)."""
        self.record(value)
        return self.detect_trend()
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "data_points": len(self._history),
            "trend_log": len(self._trend_log),
            "last_trend": self._trend_log[-1] if self._trend_log else None,
        }

# 兼容别名
TrendPredictor = TrendDetector
