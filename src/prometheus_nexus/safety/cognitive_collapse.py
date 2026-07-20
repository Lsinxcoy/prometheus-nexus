"""CognitiveCollapse — 认知坍缩检测.

基于:
- MiMo Knowledge #39: "认知坍缩=相变,超过临界阈值后能力突然崩溃"
  - 委托比率: 追踪AI辅助依赖度
  - 相变检测: 检测突然的能力下降
  - 趋势分析: 比较近期与历史委托模式
  - 告警分级: warning/critical

算法:
    detect():
        1. 计算近期委托均值
        2. 计算历史委托均值
        3. 检测相变(近期>历史×1.5)
        4. 检查是否超过阈值
        5. 返回检测结果

复杂度:
    detect(): O(R) 其中R=分析窗口
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import math
from collections import deque


class CognitiveCollapse:
    """认知坍缩检测器.
    
    检测过度依赖外部推理导致的相变崩溃.
    """
    
    def __init__(self, threshold: float = 0.7, window_size: int = 10,
                 phase_change_multiplier: float = 1.5):
        """初始化.
        
        Args:
            threshold: 坍缩阈值
            window_size: 分析窗口大小
            phase_change_multiplier: 相变倍数
        """
        self._threshold = threshold
        self._window_size = window_size
        self._phase_mult = phase_change_multiplier
        
        self._delegation_history: deque = deque(maxlen=100)
        self._complexity_history: deque = deque(maxlen=100)
        self._alerts: list[dict] = []
        self._detection_count = 0
    
    def record_delegation(self, task_complexity: float, ai_assistance_level: float):
        """记录委托数据.
        
        Args:
            task_complexity: 任务复杂度(0-1)
            ai_assistance_level: AI辅助水平(0-1)
        """
        self._delegation_history.append({
            "complexity": task_complexity,
            "assistance": ai_assistance_level,
        })
        self._complexity_history.append(task_complexity)
    
    def detect(self) -> dict:
        """检测认知坍缩.
        
        Returns:
            dict: 检测结果
        """
        self._detection_count += 1
        
        history = list(self._delegation_history)
        
        if len(history) < self._window_size:
            return {
                "collapsed": False,
                "reason": "insufficient_data",
                "samples": len(history),
                "required": self._window_size,
            }
        
        # 近期窗口
        recent = history[-self._window_size:]
        recent_delegation = sum(h["assistance"] for h in recent) / len(recent)
        recent_complexity = sum(h["complexity"] for h in recent) / len(recent)
        
        # 历史对比
        older = history[:-self._window_size] if len(history) > self._window_size else []
        older_delegation = 0
        if older:
            older_delegation = sum(h["assistance"] for h in older) / len(older)
        
        # 相变检测
        phase_change = False
        if older_delegation > 0 and recent_delegation > older_delegation * self._phase_mult:
            phase_change = True
        
        # 坍缩判断
        collapsed = False
        reason = "normal"
        severity = "none"
        
        if recent_delegation > self._threshold:
            if phase_change:
                collapsed = True
                reason = "phase_change_detected"
                severity = "critical"
            else:
                reason = "threshold_exceeded"
                severity = "warning"
        
        # 任务复杂度分析
        complexity_ratio = 0
        if recent_complexity > 0:
            complexity_ratio = recent_delegation / recent_complexity
            if complexity_ratio > 2.0:
                reason = "assistance_exceeds_complexity"
                severity = max(severity, "warning", key=lambda x: {"none": 0, "warning": 1, "critical": 2}.get(x, 0))
        
        if severity != "none":
            alert = {
                "severity": severity,
                "reason": reason,
                "recent_delegation": recent_delegation,
                "older_delegation": older_delegation,
                "phase_change": phase_change,
                "complexity_ratio": complexity_ratio,
            }
            self._alerts.append(alert)
        
        return {
            "collapsed": collapsed,
            "severity": severity,
            "reason": reason,
            "recent_delegation": round(recent_delegation, 4),
            "older_delegation": round(older_delegation, 4),
            "phase_change": phase_change,
            "threshold": self._threshold,
            "complexity_ratio": round(complexity_ratio, 4),
        }
    
    def get_risk_score(self) -> float:
        """获取风险评分(0-1).
        
        Returns:
            float: 风险分数
        """
        if len(self._delegation_history) < 5:
            return 0.0
        
        recent = list(self._delegation_history)[-5:]
        avg = sum(h["assistance"] for h in recent) / len(recent)
        
        # 接近阈值的风险
        if avg > self._threshold:
            return min(1.0, (avg - self._threshold) / (1 - self._threshold) + 0.5)
        
        return max(0, (avg - 0.3) / (self._threshold - 0.3) * 0.5)
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "history": len(self._delegation_history),
            "detections": self._detection_count,
            "alerts": len(self._alerts),
            "risk_score": round(self.get_risk_score(), 4),
            "threshold": self._threshold,
        }
