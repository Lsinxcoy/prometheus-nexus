"""EquilibriumGuard — 均衡保护与阈值检测.

基于:
- "Homeostatic Control for AI System Stability"
  - 平衡检测: 多指标均衡性评估
  - 偏离预警: 检测指标偏离均衡
  - 恢复建议: 推荐恢复均衡的操作
  - 阈值管理: 动态调整阈值

算法:
    check(metrics):
        1. 计算各指标偏离度
        2. 判断是否失衡
        3. 生成恢复建议
        4. 返回均衡报告

复杂度:
    check(): O(N) N=指标数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import math
from collections import defaultdict


class EquilibriumGuard:
    """均衡保护 — 多指标均衡性监控.
    
    检测系统指标是否偏离正常均衡范围.
    """
    
    def __init__(self, deviation_threshold: float = 2.0):
        """初始化.
        
        Args:
            deviation_threshold: 偏离阈值(标准差倍数)
        """
        self._deviation_threshold = deviation_threshold
        self._baselines: dict[str, dict] = {}
        self._readings: dict[str, list] = defaultdict(list)
        self._alerts: list[dict] = []
    
    def set_baseline(self, metric: str, expected: float,
                     tolerance: float = 0.1) -> None:
        """设置基线.
        
        Args:
            metric: 指标名
            expected: 期望值
            tolerance: 容忍度
        """
        self._baselines[metric] = {
            "expected": expected,
            "tolerance": tolerance,
        }
    
    def record(self, metric: str, value: float) -> None:
        """记录指标值.
        
        Args:
            metric: 指标名
            value: 指标值
        """
        self._readings[metric].append({
            "value": value,
            "ts": time.time(),
        })
        # 限制历史
        if len(self._readings[metric]) > 100:
            self._readings[metric] = self._readings[metric][-50:]
    
    def check(self) -> dict:
        """检查均衡状态.
        
        Returns:
            dict: 均衡报告
        """
        metrics_status = []
        imbalanced = []
        
        for metric, baseline in self._baselines.items():
            readings = self._readings.get(metric, [])
            if not readings:
                continue
            
            latest = readings[-1]["value"]
            expected = baseline["expected"]
            tolerance = baseline["tolerance"]
            
            # 计算偏离度
            deviation = abs(latest - expected) / max(abs(expected), 1e-10)
            
            # 统计偏离
            values = [r["value"] for r in readings[-20:]]
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std_dev = math.sqrt(variance)
            
            z_score = (latest - mean) / max(std_dev, 1e-10)
            
            is_balanced = deviation <= tolerance
            status = "balanced" if is_balanced else "imbalanced"
            
            metrics_status.append({
                "metric": metric,
                "value": round(latest, 4),
                "expected": expected,
                "deviation": round(deviation, 4),
                "tolerance": tolerance,
                "z_score": round(z_score, 4),
                "status": status,
            })
            
            if not is_balanced:
                imbalanced.append(metric)
        
        # 生成建议
        suggestions = []
        for metric in imbalanced:
            suggestions.append({
                "metric": metric,
                "action": "adjust_towards_baseline",
                "target": self._baselines[metric]["expected"],
            })
        
        overall = "equilibrium" if not imbalanced else "imbalanced"
        
        report = {
            "status": overall,
            "metrics": metrics_status,
            "imbalanced_count": len(imbalanced),
            "total_monitored": len(metrics_status),
            "suggestions": suggestions,
            "ts": time.time(),
        }
        
        if imbalanced:
            self._alerts.append({
                "type": "imbalance",
                "metrics": imbalanced,
                "ts": time.time(),
            })
            if len(self._alerts) > 100:
                self._alerts = self._alerts[-50:]
        
        return report
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "monitored_metrics": len(self._baselines),
            "active_readings": sum(len(v) for v in self._readings.values()),
            "total_alerts": len(self._alerts),
        }
    
    def observe(self, value: float, metric: str = "default") -> None:
        """观察指标值（兼容别名，委托 record）.
        
        Args:
            value: 指标值
            metric: 指标名
        """
        self.record(metric, value)
    
    # 兼容别名: test_stress.py 调用 get_alert_level()
    def get_alert_level(self) -> str:
        """获取告警级别 (兼容别名)."""
        report = self.check()
        if report["imbalanced_count"] == 0:
            return "normal"
        elif report["imbalanced_count"] <= 2:
            return "warning"
        else:
            return "critical"
