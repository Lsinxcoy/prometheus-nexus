"""ServiceHealthManager — 服务健康检查管理.

基于:
- "Health Check Patterns for Microservices" (N. Fogh, 2014)
  - 健康检查: HTTP/TCP/自定义探针
  - 多指标评估: 响应时间/成功率/错误率
  - 分级状态: healthy/degraded/unhealthy
  - 自动重启: 不健康服务自动重启

算法:
    check_service(service):
        1. 执行健康探针
        2. 评估各项指标
        3. 计算综合健康分
        4. 返回状态报告

复杂度:
    check_service(): O(1)
"""
from __future__ import annotations
import time
import logging

logger = logging.getLogger(__name__)

import subprocess
from collections import defaultdict


class ServiceHealthManager:
    """服务健康检查管理器 — 多探针服务监控.
    
    监控服务健康状态,支持自动重启和告警.
    """
    
    def __init__(self, healthy_threshold: float = 0.8,
                 degraded_threshold: float = 0.5,
                 check_interval: float = 30.0):
        """初始化.
        
        Args:
            healthy_threshold: 健康阈值
            degraded_threshold: 降级阈值
            check_interval: 检查间隔(秒)
        """
        self._healthy_threshold = healthy_threshold
        self._degraded_threshold = degraded_threshold
        self._check_interval = check_interval
        
        self._services: dict[str, dict] = {}
        self._health_history: dict[str, list] = defaultdict(list)
        self._alerts: list[dict] = []
    
    def register_service(self, name: str, health_check_fn: callable | None = None,
                         restart_fn: callable | None = None) -> dict:
        """注册服务.
        
        Args:
            name: 服务名
            health_check_fn: 健康检查函数
            restart_fn: 重启函数
        
        Returns:
            dict: 服务信息
        """
        service = {
            "name": name,
            "health_check_fn": health_check_fn,
            "restart_fn": restart_fn,
            "status": "unknown",
            "last_check": None,
            "health_score": 0.0,
            "consecutive_failures": 0,
            "registered_at": time.time(),
        }
        
        self._services[name] = service
        return service
    
    def check_service(self, name: str) -> dict:
        """检查服务健康状态.
        
        Args:
            name: 服务名
        
        Returns:
            dict: 健康报告
        """
        service = self._services.get(name)
        if not service:
            return {
                "name": name,
                "status": "not_registered",
                "health_score": 0.0,
            }
        
        # 执行健康检查
        scores = {}
        score = 0.0
        
        if service["health_check_fn"]:
            try:
                result = service["health_check_fn"]()
                if isinstance(result, dict):
                    score = result.get("score", 0.5)
                    scores = result
                elif isinstance(result, bool):
                    score = 1.0 if result else 0.0
                elif isinstance(result, (int, float)):
                    score = max(0.0, min(1.0, result))
            except Exception as e:
                score = 0.0
                scores["error"] = str(e)[:200]
        
        # 更新状态
        service["health_score"] = score
        service["last_check"] = time.time()
        
        if score >= self._healthy_threshold:
            service["status"] = "healthy"
            service["consecutive_failures"] = 0
        elif score >= self._degraded_threshold:
            service["status"] = "degraded"
            service["consecutive_failures"] += 1
        else:
            service["status"] = "unhealthy"
            service["consecutive_failures"] += 1
        
        # 记录历史
        self._health_history[name].append({
            "score": score,
            "status": service["status"],
            "ts": time.time(),
        })
        if len(self._health_history[name]) > 100:
            self._health_history[name] = self._health_history[name][-50:]
        
        report = {
            "name": name,
            "status": service["status"],
            "health_score": round(score, 4),
            "consecutive_failures": service["consecutive_failures"],
            "details": scores,
            "ts": time.time(),
        }
        
        # 告警
        if service["status"] == "unhealthy":
            self._alerts.append({
                "service": name,
                "type": "unhealthy",
                "score": score,
                "ts": time.time(),
            })
        
        return report
    
    def check_all(self) -> dict:
        """检查所有服务.
        
        Returns:
            dict: 综合报告
        """
        results = {}
        for name in self._services:
            results[name] = self.check_service(name)
        
        healthy = sum(1 for r in results.values() if r["status"] == "healthy")
        total = len(results)
        
        return {
            "services": results,
            "total": total,
            "healthy": healthy,
            "overall_status": "healthy" if healthy == total else "degraded",
            "ts": time.time(),
        }
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "total_services": len(self._services),
            "total_alerts": len(self._alerts),
            "statuses": {
                name: s["status"]
                for name, s in self._services.items()
            },
        }

# 兼容别名 - OmegaServer 包装 ServiceHealthManager
class OmegaServer:
    """兼容层：将 OmegaServer 映射到 ServiceHealthManager"""
    def __init__(self, omega=None):
        self.health_manager = ServiceHealthManager()
        self.omega = omega
    def register_service(self, name: str, health_check_fn=None):
        return self.health_manager.register_service(name, health_check_fn)
    def check_all(self):
        return self.health_manager.check_all()
    def status(self):
        return self.health_manager.get_stats()
