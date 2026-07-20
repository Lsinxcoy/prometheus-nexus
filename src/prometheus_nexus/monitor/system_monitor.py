"""SystemMonitor — 系统实时监控.

基于:
- "Prometheus Metrics with Alerting Rules" (CNCF)
  - 指标采集: 多指标支持(内存/CPU/请求/延迟)
  - 滑动窗口: 最近N个数据点计算统计
  - 异常检测: 均值+标准差阈值
  - 告警管理: 分级告警+历史追溯

算法:
    record(metric, value):
        1. 添加到滑动窗口
        2. 计算统计量(均值/标准差)
        3. 检测异常(>2σ)
        4. 触发告警
    
    get_health():
        1. 检查最近告警
        2. 评估系统状态
        3. 返回健康等级

复杂度:
    record(): O(W) 其中W=窗口大小
    get_health(): O(A) 其中A=告警数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import math
from collections import deque


class SystemMonitor:
    """系统监控器.
    
    多指标采集+异常检测+告警.
    """
    
    def __init__(self, window_size: int = 100, alert_std_multiplier: float = 2.0,
                 max_alerts: int = 50):
        """初始化.
        
        Args:
            window_size: 滑动窗口大小
            alert_std_multiplier: 告警标准差倍数
            max_alerts: 最大告警数
        """
        self._start_time = time.time()
        self._window_size = window_size
        self._alert_std = alert_std_multiplier
        self._max_alerts = max_alerts
        
        self._metrics: dict[str, deque] = {}
        self._alerts: list[dict] = []
        self._stats_cache: dict[str, dict] = {}
        self._cache_time = 0.0
    
    def record(self, metric: str, value: float) -> dict | None:
        """记录指标.
        
        Args:
            metric: 指标名称
            value: 指标值
        
        Returns:
            dict: 告警信息(如果触发)
        """
        if metric not in self._metrics:
            self._metrics[metric] = deque(maxlen=self._window_size)
        
        self._metrics[metric].append((time.time(), value))
        self._cache_time = 0  # 失效缓存
        
        # 异常检测(至少10个数据点)
        history = list(self._metrics[metric])
        if len(history) >= 10:
            values = [v for _, v in history]
            stats = self._compute_stats(values)
            self._stats_cache[metric] = stats
            
            # 标准差检测
            if stats["std"] > 0 and value > stats["mean"] + self._alert_std * stats["std"]:
                alert = {
                    "metric": metric,
                    "value": value,
                    "mean": stats["mean"],
                    "std": stats["std"],
                    "deviation": (value - stats["mean"]) / stats["std"],
                    "level": "critical" if value > stats["mean"] + 3 * stats["std"] else "warning",
                    "ts": time.time(),
                }
                self._alerts.append(alert)
                
                # 限制告警数
                if len(self._alerts) > self._max_alerts:
                    self._alerts = self._alerts[-self._max_alerts:]
                
                return alert
        
        return None
    
    def _compute_stats(self, values: list[float]) -> dict:
        """计算统计量.
        
        Args:
            values: 数据列表
        
        Returns:
            dict: 统计量
        """
        n = len(values)
        mean = sum(values) / n
        
        # 标准差
        variance = sum((v - mean) ** 2 for v in values) / n
        std = math.sqrt(variance)
        
        # 百分位数
        sorted_vals = sorted(values)
        p25 = sorted_vals[n // 4]
        p50 = sorted_vals[n // 2]
        p75 = sorted_vals[3 * n // 4]
        p95 = sorted_vals[int(n * 0.95)]
        
        return {
            "count": n,
            "mean": round(mean, 4),
            "std": round(std, 4),
            "min": min(values),
            "max": max(values),
            "p25": p25,
            "p50": p50,
            "p75": p75,
            "p95": p95,
        }
    
    def get_metric_stats(self, metric: str) -> dict:
        """获取指标统计.
        
        Args:
            metric: 指标名称
        
        Returns:
            dict: 统计信息
        """
        if metric in self._stats_cache:
            return self._stats_cache[metric]
        
        if metric not in self._metrics:
            return {"error": "metric_not_found"}
        
        values = [v for _, v in self._metrics[metric]]
        if not values:
            return {"count": 0}
        
        stats = self._compute_stats(values)
        self._stats_cache[metric] = stats
        return stats
    
    def get_uptime(self) -> float:
        """获取运行时间(秒)."""
        return time.time() - self._start_time
    
    def get_health(self) -> str:
        """获取健康状态.
        
        Returns:
            str: healthy/degraded/critical
        """
        now = time.time()
        
        # 最近5分钟的告警
        recent = [a for a in self._alerts if now - a["ts"] < 300]
        critical = [a for a in recent if a.get("level") == "critical"]
        
        if len(critical) > 3:
            return "critical"
        if len(recent) > 5:
            return "degraded"
        
        return "healthy"
    
    def clear_stale_alerts(self, max_age: float = 600) -> int:
        """清理过期告警.
        
        Args:
            max_age: 最大年龄(秒)
        
        Returns:
            int: 清理数量
        """
        now = time.time()
        original = len(self._alerts)
        self._alerts = [a for a in self._alerts if now - a["ts"] < max_age]
        return original - len(self._alerts)
    
    def get_stats(self) -> dict:
        """获取统计."""
        health = self.get_health()
        recent_alerts = len([a for a in self._alerts if time.time() - a["ts"] < 300])
        
        return {
            "uptime_s": round(self.get_uptime(), 1),
            "metrics_tracked": len(self._metrics),
            "metric_names": list(self._metrics.keys()),
            "total_alerts": len(self._alerts),
            "recent_alerts": recent_alerts,
            "health": health,
        }
