"""omega 包 — Omega(上帝类)装配层外置.

真拆 life.py 的装配/子系统逻辑集中于此, 逐步收敛 5443 行上帝类。
"""

from prometheus_nexus.omega.assembly import register_all_mechanisms
from prometheus_nexus.omega.heartbeat import run_heartbeat
from prometheus_nexus.omega.health import collect_component_health, compute_health
from prometheus_nexus.omega.monitor import get_mechanism_consumption, get_semantic_health

__all__ = ["register_all_mechanisms", "run_heartbeat", "collect_component_health",
          "compute_health", "get_mechanism_consumption", "get_semantic_health"]
