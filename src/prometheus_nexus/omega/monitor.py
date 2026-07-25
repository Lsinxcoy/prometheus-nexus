"""omega 包 — 监控诊断统计逻辑外置.

真拆 life.py 第四步(最高收益高风险项, 用户授权):
把 Omega.get_mechanism_consumption(4932-4963) 纯搬迁到 omega/monitor.py。
该方法是基于 Nexus 快照的静默机制分类统计, 与调度解耦, 可外置收敛上帝类。

纯搬迁, 行为逐行不变。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_mechanism_consumption(self) -> dict:
    """机制消费/健康统一视图 — 委托 Nexus 真相源 (第三层监控统合).

    Nexus 已统辖全部基本盘 + 动态层 + 7管道, 其 get_monitor_snapshot() 是机制
    消费的唯一权威真相源. 本方法不再重复聚合 6 载体(机制层已在 Nexus),
    仅基于 Nexus 数据做静默机制诊断分类(有价值的诊断逻辑保留).

    返回 {total, consumed, rate, by_carrier, silent_mechanisms, silent_by_category}
    """
    try:
        nx = getattr(self, "nexus", None)
        if nx is None:
            return {"total": 0, "consumed": 0, "rate": 0.0, "by_carrier": {}}
        snap = nx.get_monitor_snapshot()
        # 静默机制分类(silent_mechanisms 来自 Nexus 真相源, 更准)
        silent = snap.get("silent_mechanisms", [])
        silent_by_category = {
            "test_residue": [], "orphan_registry": [],
            "dormant_ok": [], "trigger_missing": [],
        }
        for name in silent:
            low = name.lower()
            if ("test" in low or "tmp" in low or low.endswith("_p")
                    or low.startswith(("p_", "c1_", "c2_", "bad_", "z_"))):
                silent_by_category["test_residue"].append(name)
            elif low.startswith(("learn_", "scan_", "fetch_")):
                silent_by_category["orphan_registry"].append(name)
            elif any(k in low for k in ("explore", "pending", "speculative",
                                        "candidate", "semantic_evo", "evo_g")):
                silent_by_category["dormant_ok"].append(name)
            else:
                silent_by_category["trigger_missing"].append(name)
        return {
            "total": snap["mechanisms"],
            "consumed": snap["consumed"],
            "rate": round(snap["rate"], 4),
            "dynamic_count": snap["dynamic"],
            "by_category": snap.get("by_category", {}),
            "route_overrides": snap.get("route_overrides", {}),
            "active_dynamic": snap.get("active_dynamic", []),
            "pruned_disabled": snap.get("pruned_disabled", []),
            "silent_mechanisms": silent,
            "silent_count": len(silent),
            "silent_by_category": silent_by_category,
            "by_carrier": {"nexus": {"total": snap["mechanisms"],
                                     "consumed": snap["consumed"]}},
        }
    except Exception as e:
        logger.debug("get_mechanism_consumption failed: %s", e)
        return {"total": 0, "consumed": 0, "rate": 0.0, "by_carrier": {}}


def get_semantic_health(self) -> dict:
    """Tier 3: 学习语义相关性 — 近期节点 utility 分布, 检测'是否在学垃圾'.

    返回 low_utility_ratio (utility<0.1 占比) 与 kta_untranslated (未消化高utility知识).
    (原 Omega.get_semantic_health 的纯搬迁版本, 行为逐行不变)
    """
    try:
        from prometheus_nexus.foundation.schema import NodeType

        store = getattr(self, "store", None)
        if store is None:
            return {"low_utility_ratio": 0.0, "sampled": 0, "kta_untranslated": 0}
        # 采样近期 FACT/INSIGHT/CONCEPT/PATTERN 节点 (近期学习主体)
        utils: list[float] = []
        for nt in (NodeType.FACT, NodeType.INSIGHT, NodeType.CONCEPT, NodeType.PATTERN):
            try:
                nodes = store.get_nodes_by_type(nt, limit=200)
                for n in nodes:
                    u = getattr(n, "utility", None)
                    if u is not None:
                        utils.append(u)
            except Exception:
                continue
        sampled = len(utils)
        low = sum(1 for u in utils if u < 0.1)
        low_ratio = round(low / max(1, sampled), 4)
        # KTA 未翻译高utility节点 (知识未消化)
        kta = 0
        try:
            kta_hint = self.knowledge_to_mechanism.scan_for_opportunities(
                store=store, utility_threshold=0.6)
            kta = kta_hint.get("untranslated_count", 0) or 0
        except Exception:
            pass
        return {"low_utility_ratio": low_ratio, "sampled": sampled,
                "low_utility_count": low, "kta_untranslated": kta}
    except Exception as e:
        logger.debug("get_semantic_health failed: %s", e)
        return {"low_utility_ratio": 0.0, "sampled": 0, "kta_untranslated": 0}
