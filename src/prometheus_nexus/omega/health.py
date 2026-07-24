"""omega 包 — 系统健康采集/聚合逻辑外置.

真拆 life.py 第三步(最高收益高风险项, 用户授权):
把 Omega._collect_component_health(4908-4930) + _compute_health(5206-5227)
纯搬迁到 omega/health.py。这两段是独立的健康统计/聚合逻辑,
与主循环调度解耦, 可外置收敛上帝类。

纯搬迁, 行为逐行不变。
"""

from __future__ import annotations

import logging
from typing import Any

from prometheus_nexus.foundation.schema import AlertLevel

logger = logging.getLogger(__name__)


def collect_component_health(self) -> tuple[dict, list[str]]:
    """安全采集各组件健康.

    Returns:
        (details, failed): details[name]=组件统计或{'error':...};
        failed=探测失败的组件名列表(供 compute_health 聚合)
    """
    details: dict = {}
    failed: list[str] = []
    for name, method in self.COMPONENT_HEALTH_PROBES:
        attr = method.split(".")[-1]
        try:
            comp = getattr(self, name, None)
            if comp is None or not hasattr(comp, attr):
                details[name] = {"error": f"{name} not initialized or missing method"}
                failed.append(name)
                continue
            details[name] = getattr(comp, attr)()
        except Exception as e:
            details[name] = {"error": str(e)[:50]}
            failed.append(name)
    return details, failed


def compute_health(self, failed_components: list[str] | None = None) -> str:
    """聚合系统健康等级.

    优先级: empty(空库) > critical(equilibrium RED 或组件失败达阈值)
    > degraded(组件失败) > healthy.
    """
    try:
        if self.store.get_node_count() == 0:
            return "empty"
        eq = self.equilibrium.get_alert_level()
        if eq == AlertLevel.RED:
            return "critical"
        if eq == AlertLevel.ORANGE:
            return "degraded"
        if failed_components is None:
            _, failed_components = collect_component_health(self)
        if len(failed_components) >= self.HEALTH_CRITICAL_COMPONENT_FAILURES:
            return "critical"
        if failed_components:
            return "degraded"
        return "healthy"
    except Exception:
        logger.warning("Health status check failed, returning unknown")
        return "unknown"
