"""retrieval — 信任感知检索标注(架构优化: 从 life.py 外置器官).

外置动机
--------
life.py 的 _recall_with_trust 体内部(2468-2557)含一段"信任状态标注 + 降权"核心算法:
遍历 recall 命中, 读节点的 tristate 信任态(HAS/NOT_HAS/UNCERTAIN), 标注并降权,
再按分数排序截断。这段逻辑纯函数式(输入 hits + store, 输出标注后 hits),
本不属于上帝的调度流程, 是可外置独立测试与复用的器官。

按"保留上帝调度权、外置器官"原则:
- annotate_trust(hits, store, limit): 纯算法外置到本模块, 可无 Omega 实例化单测。
- 反馈环路(recall→learn 知识缺口)留在 life.py(属调度逻辑, 不外置)。
- life.py._recall_with_trust 改为: 调 recall → annotate_trust → 组装 + 推 feedback,
  行为逐行不变(由 test_omega_smoke / 本模块单测双重保证)。

依赖
----
仅依赖 store.read_node(node_id) -> Node|None 与 Node.trust_state 字段,
可接受任意实现(read_node 返回 Node 或 None) — 测试中用 fake store。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def annotate_trust(
    hits: list[Any],
    store: Any,
    limit: int = 10,
) -> tuple[list[Any], dict[str, int]]:
    """对 recall 命中做信任态标注与降权, 返回 (标注后hits, 信任统计).

    Args:
        hits: SearchHit 列表(每个含 .node_id, .score, .metadata)
        store: 含 read_node(node_id)->Node|None 的存储对象
        limit: 排序后截断条数

    Returns:
        (filtered_hits, trust_metadata):
        - filtered_hits: 标注 + 降权 + 按 score 降序截断后的命中列表
        - trust_metadata: {"has": n, "not_has": n, "uncertain": n, "unknown": n}
    """
    trust_metadata: dict[str, int] = {"has": 0, "not_has": 0, "uncertain": 0, "unknown": 0}
    filtered_hits: list[Any] = []

    try:
        for hit in hits:
            node = None
            try:
                node = store.read_node(hit.node_id)
            except Exception as e:  # pragma: no cover - store 异常极少见
                logger.warning("annotate_trust: read_node failed: %s", e)

            trust_state = "unknown"
            if node is not None:
                try:
                    trust_state = getattr(node, "trust_state", "unknown") or "unknown"
                except Exception:
                    logger.warning("annotate_trust: read trust_state failed, default unknown")
                    trust_state = "unknown"

            hit.metadata["trust_state"] = trust_state
            trust_metadata[trust_state] = trust_metadata.get(trust_state, 0) + 1

            if trust_state == "not_has":
                # 已知缺失: 保留但大幅降权
                hit.metadata["suppressed"] = True
                hit.score *= 0.3
                hit.metadata["note"] = "known_absent"
            elif trust_state == "uncertain":
                # 未验证: 标记并中度降权
                hit.metadata["unverified"] = True
                hit.score *= 0.7
                hit.metadata["note"] = "unverified"
            # trust_state == "has": 无需修改

            filtered_hits.append(hit)

        filtered_hits.sort(key=lambda h: h.score, reverse=True)
        filtered_hits = filtered_hits[:limit]

    except Exception as e:  # pragma: no cover - 遍历异常极少见
        logger.error("annotate_trust: filtering failed: %s", e)
        filtered_hits = hits[:limit]

    return filtered_hits, trust_metadata


__all__ = ["annotate_trust"]
