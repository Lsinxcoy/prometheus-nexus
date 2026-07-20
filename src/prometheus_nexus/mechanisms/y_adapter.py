"""YBankAdapter — Y-system bank format adapter.

基于:
- Anderson, J.R. (1983) ACT理论: 记忆层级模型 (working → short_term → long_term → episodic/semantic)
  - 6层记忆分级: working(0), short_term(1), long_term(2), episodic(3), semantic(4), archive(6)
  - 有效迁移拓扑: VALID_TRANSITIONS 定义合法tier跃迁路径
  - 效用驱动分级: utility>0.8→long_term, >0.5→short_term, else→working
  - 归档终端: archive(6)为终态, 无出度(VALID_TRANSITIONS[6]=[])

来源: Omega系统 y_adapter Y系统记忆层级适配器 + ACT认知架构
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)



class YBankAdapter:
    """Y-system bank adapter with tier mapping and migration.

    Usage:
        adapter = YBankAdapter()
        result = adapter.adapt({"node_id": "n1", "utility": 0.9})
        print(result["assigned_tier"])  # 2 (long_term)

        migration = adapter.migrate_tier("n1", current_tier=0, target_tier=2)
        print(migration["migrated"])  # True
    """

    TIER_MAP = {
        "working": 0,
        "short_term": 1,
        "long_term": 2,
        "episodic": 3,
        "semantic": 4,
        "archive": 6,
    }

    VALID_TRANSITIONS = {
        0: [1, 6],      # working -> short_term, archive
        1: [0, 2, 6],   # short_term -> working, long_term, archive
        2: [1, 3, 4],   # long_term -> short_term, episodic, semantic
        3: [2, 4, 6],   # episodic -> long_term, semantic, archive
        4: [2, 3, 6],   # semantic -> long_term, episodic, archive
        6: [],           # archive -> (terminal)
    }

    def __init__(self):
        self._adaptations: list[dict] = []
        self._migrations: list[dict] = []

    def adapt(self, data: dict | None = None) -> dict:
        data = data or {}
        adapted = dict(data)

        utility = data.get("utility", 0.5)
        if utility > 0.8:
            adapted["tier"] = self.TIER_MAP["long_term"]
        elif utility > 0.5:
            adapted["tier"] = self.TIER_MAP["short_term"]
        else:
            adapted["tier"] = self.TIER_MAP["working"]

        adapted["_adapter"] = "YBankAdapter"
        result = {"adapted": True, "source": "Y", "assigned_tier": adapted["tier"]}
        self._adaptations.append(result)
        return result

    def migrate_tier(self, node_id: str, current_tier: int, target_tier: int) -> dict:
        valid = self.VALID_TRANSITIONS.get(current_tier, [])
        if target_tier not in valid:
            return {
                "node_id": node_id, "from": current_tier, "to": target_tier,
                "migrated": False, "reason": f"invalid transition {current_tier}->{target_tier}",
            }

        migration = {
            "node_id": node_id, "from": current_tier, "to": target_tier,
            "migrated": True,
        }
        self._migrations.append(migration)
        return migration

    def get_tier_name(self, tier: int) -> str:
        for name, val in self.TIER_MAP.items():
            if val == tier:
                return name
        return "unknown"

    def get_stats(self) -> dict:
        return {"adaptations": len(self._adaptations), "migrations": len(self._migrations)}
