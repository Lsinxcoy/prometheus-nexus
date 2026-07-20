"""DynamicScaler — 资源自适应动态缩放.

基于:
- "PID-based Auto-scaling" (Berardi et al., 2015)
  - 比例控制: 偏差越大,缩放力度越大
  - 积分控制: 累积偏差消除稳态误差
  - 微分控制: 预测趋势,抑制超调
  - 防震荡: 冷却期内禁止反向缩放

算法:
    scale(dimension, load):
        1. 计算偏差 = 目标负载 - 当前负载
        2. PID计算调整量
        3. 检查冷却期
        4. 应用缩放因子
        5. 更新历史

复杂度:
    scale(): O(W) 其中W=窗口大小
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import math


class DynamicScaler:
    """资源自适应动态缩放 — PID控制.
    
    多维度资源管理,防止缩放震荡.
    """
    
    def __init__(self, scale_up_threshold: float = 0.8, scale_down_threshold: float = 0.3,
                 kp: float = 1.0, ki: float = 0.1, kd: float = 0.05,
                 cooldown_seconds: float = 30.0, max_scale: float = 4.0, min_scale: float = 0.25):
        """初始化.
        
        Args:
            scale_up_threshold: 扩容阈值
            scale_down_threshold: 缩容阈值
            kp: 比例增益
            ki: 积分增益
            kd: 微分增益
            cooldown_seconds: 冷却时间(秒)
            max_scale: 最大缩放因子
            min_scale: 最小缩放因子
        """
        self._up_threshold = scale_up_threshold
        self._down_threshold = scale_down_threshold
        self._kp = kp
        self._ki = ki
        self._kd = kd
        self._cooldown = cooldown_seconds
        self._max_scale = max_scale
        self._min_scale = min_scale
        
        self._scales: list[dict] = []
        self._current_scale: dict[str, float] = {"compute": 1.0, "memory": 1.0, "tokens": 1.0}
        self._load_history: dict[str, list[dict]] = {"compute": [], "memory": [], "tokens": []}
        self._last_scale_time: dict[str, float] = {}
        self._last_direction: dict[str, str] = {}
        self._integral: dict[str, float] = {"compute": 0, "memory": 0, "tokens": 0}
        self._prev_error: dict[str, float] = {"compute": 0, "memory": 0, "tokens": 0}
    
    def scale(self, dimension: str, load: float) -> dict:
        """执行缩放决策.
        
        Args:
            dimension: 资源维度 (compute/memory/tokens)
            load: 当前负载 [0, 1]
        
        Returns:
            dict: 缩放结果
        """
        now = time.time()
        
        # Auto-initialize dimension if not seen before
        if dimension not in self._current_scale:
            self._current_scale[dimension] = 1.0
            self._integral[dimension] = 0.0
            self._prev_error[dimension] = 0.0
            self._load_history[dimension] = []
        
        # 记录负载
        if dimension not in self._load_history:
            self._load_history[dimension] = []
        
        self._load_history[dimension].append({"value": load, "ts": now})
        
        # 限制历史大小
        if len(self._load_history[dimension]) > 100:
            self._load_history[dimension] = self._load_history[dimension][-50:]
        
        # 计算近期平均负载
        recent = [h["value"] for h in self._load_history[dimension][-10:]]
        avg_load = sum(recent) / len(recent) if recent else load
        
        # 确定目标负载
        target_load = 0.5  # 目标: 50%负载率
        
        # 计算偏差
        error = target_load - avg_load
        
        # 检查是否需要缩放
        needs_scale = (avg_load > self._up_threshold or avg_load < self._down_threshold)
        
        if not needs_scale:
            return {
                "dimension": dimension,
                "load": round(avg_load, 4),
                "action": "no_change",
                "scale_factor": self._current_scale.get(dimension, 1.0),
            }
        
        # 冷却期检查
        last_time = self._last_scale_time.get(dimension, 0)
        direction = "up" if avg_load > self._up_threshold else "down"
        last_dir = self._last_direction.get(dimension, "")
        
        # 同方向不需要冷却,反向需要
        if last_dir == direction and last_dir != "":
            if now - last_time < self._cooldown:
                return {
                    "dimension": dimension,
                    "load": round(avg_load, 4),
                    "action": "cooldown",
                    "scale_factor": self._current_scale.get(dimension, 1.0),
                }
        
        # PID计算调整量
        self._integral[dimension] += error
        dt = now - last_time if last_time > 0 else 1.0
        derivative = (error - self._prev_error[dimension]) / max(dt, 0.001)
        
        adjustment = (self._kp * error + 
                      self._ki * self._integral[dimension] + 
                      self._kd * derivative)
        
        # 计算新缩放因子
        current = self._current_scale.get(dimension, 1.0)
        new_scale = current * (1 + adjustment * 0.1)
        
        # 限制范围
        new_scale = max(self._min_scale, min(self._max_scale, new_scale))
        
        # 应用缩放
        self._current_scale[dimension] = new_scale
        self._last_scale_time[dimension] = now
        self._last_direction[dimension] = direction
        self._prev_error[dimension] = error
        
        # 记录
        self._scales.append({
            "dimension": dimension,
            "from_scale": round(current, 4),
            "to_scale": round(new_scale, 4),
            "load": round(avg_load, 4),
            "direction": direction,
            "ts": now,
        })
        if len(self._scales) > 500:
            self._scales = self._scales[-250:]
        
        return {
            "dimension": dimension,
            "load": round(avg_load, 4),
            "action": direction,
            "from_scale": round(current, 4),
            "to_scale": round(new_scale, 4),
            "adjustment": round(adjustment, 4),
        }
    
    def get_load_trend(self, dimension: str, window: int = 10) -> str:
        """获取负载趋势.
        
        Args:
            dimension: 资源维度
            window: 窗口大小
        
        Returns:
            str: rising/stable/falling
        """
        history = self._load_history.get(dimension, [])
        if len(history) < window:
            return "unknown"
        
        recent = [h["value"] for h in history[-window:]]
        
        # 线性回归斜率
        n = len(recent)
        x_mean = (n - 1) / 2
        y_mean = sum(recent) / n
        
        numerator = sum((i - x_mean) * (recent[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return "stable"
        
        slope = numerator / denominator
        
        if slope > 0.02:
            return "rising"
        elif slope < -0.02:
            return "falling"
        return "stable"
    
    def reset_dimension(self, dimension: str):
        """重置指定维度.
        
        Args:
            dimension: 资源维度
        """
        self._current_scale[dimension] = 1.0
        self._integral[dimension] = 0
        self._prev_error[dimension] = 0
        self._last_scale_time.pop(dimension, None)
        self._last_direction.pop(dimension, None)
    
    def get_stats(self) -> dict:
        """获取统计."""
        trends = {dim: self.get_load_trend(dim) for dim in self._current_scale}
        return {
            "scale_events": len(self._scales),
            "current_scales": {k: round(v, 4) for k, v in self._current_scale.items()},
            "trends": trends,
            "dimensions": list(self._current_scale.keys()),
        }
