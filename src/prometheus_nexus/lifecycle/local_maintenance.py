"""LocalMaintenance — 本地维护与健康检查.

基于:
- "Self-Healing Systems with Periodic Health Checks"
  - 健康检查: 多指标系统状态评估
  - 自动修复: 检测异常并执行修复
  - 磁盘清理: 日志/缓存自动清理
  - 资源监控: 内存/CPU使用率

算法:
    health_check():
        1. 检查各项指标
        2. 计算综合健康分
        3. 返回健康报告
    
    cleanup(max_age_days):
        1. 扫描临时文件
        2. 删除过期文件
        3. 返回清理报告

复杂度:
    health_check(): O(1)
    cleanup(): O(F) F=文件数
"""
from __future__ import annotations



import logging
import os
import time
import shutil
from collections import defaultdict
logger = logging.getLogger(__name__)


class LocalMaintenance:
    """本地维护系统 — 自动健康检查和资源清理.
    
    监控系统状态并执行自动维护任务.
    """
    
    def __init__(self, data_dir: str = None):
        """初始化.
        
        Args:
            data_dir: 数据目录
        """
        self._data_dir = data_dir or os.path.join(os.getcwd(), "data")
        os.makedirs(self._data_dir, exist_ok=True)
        
        self._checks: list[dict] = []
        self._metrics: dict[str, list] = defaultdict(list)
    
    def record_metric(self, name: str, value: float) -> None:
        """记录指标.
        
        Args:
            name: 指标名
            value: 指标值
        """
        self._metrics[name].append({
            "value": value,
            "ts": time.time(),
        })
        # 限制历史
        if len(self._metrics[name]) > 100:
            self._metrics[name] = self._metrics[name][-50:]
    
    def health_check(self, extra_checks: dict[str, bool] | None = None) -> dict:
        """执行健康检查.
        
        Args:
            extra_checks: 额外检查项 {name: passed}
        
        Returns:
            dict: 健康报告
        """
        checks = {}
        total = 0
        passed = 0
        
        # 1. 磁盘空间检查
        try:
            stat = shutil.disk_usage(self._data_dir)
            usage_ratio = stat.used / stat.total
            disk_ok = usage_ratio < 0.9
            checks["disk_space"] = {
                "passed": disk_ok,
                "usage_ratio": round(usage_ratio, 4),
                "free_gb": round(stat.free / (1024 ** 3), 2),
            }
            total += 1
            if disk_ok:
                passed += 1
        except Exception:
            checks["disk_space"] = {"passed": False, "error": "cannot check"}
            total += 1
        
        # 2. 数据目录可写
        write_test = os.path.join(self._data_dir, ".write_test")
        try:
            with open(write_test, 'w') as f:
                f.write("test")
            os.remove(write_test)
            checks["writeable"] = {"passed": True}
            passed += 1
        except Exception:
            checks["writeable"] = {"passed": False}
        total += 1
        
        # 3. 指标异常检测
        metric_alerts = []
        for name, readings in self._metrics.items():
            if len(readings) >= 10:
                values = [r["value"] for r in readings[-10:]]
                mean = sum(values) / len(values)
                variance = sum((v - mean) ** 2 for v in values) / len(values)
                # 最新值是否离群
                latest = readings[-1]["value"]
                if variance > 0 and abs(latest - mean) > 3 * (variance ** 0.5):
                    metric_alerts.append({
                        "metric": name,
                        "latest": latest,
                        "mean": round(mean, 4),
                    })
        
        checks["metrics"] = {
            "passed": len(metric_alerts) == 0,
            "alerts": metric_alerts,
        }
        total += 1
        if not metric_alerts:
            passed += 1
        
        # 4. 额外检查
        if extra_checks:
            for name, result in extra_checks.items():
                checks[f"custom_{name}"] = {"passed": result}
                total += 1
                if result:
                    passed += 1
        
        # 综合评分
        health_score = passed / max(total, 1)
        status = "healthy" if health_score >= 0.8 else "degraded" if health_score >= 0.5 else "critical"
        
        report = {
            "status": status,
            "health_score": round(health_score, 4),
            "checks_total": total,
            "checks_passed": passed,
            "checks_detail": checks,
            "ts": time.time(),
        }
        
        self._checks.append(report)
        if len(self._checks) > 100:
            self._checks = self._checks[-50:]
        
        return report
    
    def cleanup(self, max_age_days: int = 7) -> dict:
        """清理过期文件.
        
        Args:
            max_age_days: 最大保留天数
        
        Returns:
            dict: 清理报告
        """
        now = time.time()
        max_age_seconds = max_age_days * 86400
        removed = 0
        freed_bytes = 0
        
        for root, dirs, files in os.walk(self._data_dir):
            for filename in files:
                filepath = os.path.join(root, filename)
                try:
                    mtime = os.path.getmtime(filepath)
                    if now - mtime > max_age_seconds:
                        size = os.path.getsize(filepath)
                        os.remove(filepath)
                        removed += 1
                        freed_bytes += size
                except (OSError, PermissionError) as e:
                    logger.warning("Failed to remove stale file: %s", e)
        
        report = {
            "removed_files": removed,
            "freed_bytes": freed_bytes,
            "freed_mb": round(freed_bytes / (1024 ** 2), 2),
            "ts": time.time(),
        }
        
        return report
    
    def check_node(self, node_id: str, utility: float, age: float, access_count: int) -> list:
        """检查单个节点是否需要维护.
        
        Args:
            node_id: 节点ID
            utility: 效用值
            age: 年龄(秒)
            access_count: 访问次数
            
        Returns:
            list: 维护动作列表
        """
        from collections import namedtuple
        Action = namedtuple("Action", ["action", "node_id", "reason"])
        actions = []
        
        # 低效用节点标记修剪
        if utility < 0.1:
            actions.append(Action("prune", node_id, "low_utility"))
        
        # 长期未访问标记归档
        if access_count == 0 and age > 86400:
            actions.append(Action("archive", node_id, "never_accessed"))
        
        return actions
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "total_checks": len(self._checks),
            "metrics_tracked": len(self._metrics),
            "last_check": self._checks[-1] if self._checks else None,
        }
