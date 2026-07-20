"""LearnFeedbackTracker — 追踪learned节点是否被recall命中

P0修复: Learn→Recall反馈环断裂
- learn存入节点后注册到tracker
- recall命中时标记hit
- 计算recall_hit_rate供cerebral_cortex使用
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class LearnFeedbackTracker:
    """追踪learned节点是否被recall命中

    Attributes:
        _registered: node_id -> {source, query, ts}
        _hits: node_id -> hit_count
        _query_stats: (source, query) -> {registered, hits}
    """

    def __init__(self) -> None:
        self._registered: dict[str, dict] = {}
        self._hits: dict[str, int] = defaultdict(int)
        self._query_stats: dict[tuple[str, str], dict] = defaultdict(lambda: {"registered": 0, "hits": 0})

    def register(self, node_id: str, source: str, query: str) -> None:
        """注册learned节点"""
        self._registered[node_id] = {"source": source, "query": query, "ts": time.time()}
        key = (source, query)
        self._query_stats[key]["registered"] += 1
        logger.debug(f"LearnFeedbackTracker: registered node {node_id[:8]}... for {source}:{query}")

    def mark_hit(self, node_id: str, query: str) -> None:
        """标记节点被recall命中"""
        if node_id in self._registered:
            self._hits[node_id] += 1
            entry = self._registered[node_id]
            key = (entry["source"], entry["query"])
            self._query_stats[key]["hits"] += 1
            logger.debug(f"LearnFeedbackTracker: hit node {node_id[:8]}... for query '{query}'")

    def get_hit_rate(self, source: str | None = None, query: str | None = None) -> float:
        """获取命中率

        Args:
            source: 可选，过滤特定来源
            query: 可选，过滤特定查询

        Returns:
            命中率 [0, 1]
        """
        if source is not None and query is not None:
            key = (source, query)
            stats = self._query_stats.get(key, {"registered": 0, "hits": 0})
            if stats["registered"] == 0:
                return 0.0
            return stats["hits"] / stats["registered"]

        # 全局统计
        total_registered = len(self._registered)
        if total_registered == 0:
            return 0.0
        total_hits = sum(self._hits.values())
        return total_hits / total_registered

    def get_stats(self) -> dict[str, Any]:
        """获取完整统计信息"""
        total_registered = len(self._registered)
        total_hits = sum(self._hits.values())
        hit_rate = total_hits / total_registered if total_registered > 0 else 0.0

        # 按来源统计
        source_stats: dict[str, dict] = defaultdict(lambda: {"registered": 0, "hits": 0})
        for node_id, entry in self._registered.items():
            src = entry["source"]
            source_stats[src]["registered"] += 1
            source_stats[src]["hits"] += self._hits.get(node_id, 0)

        return {
            "total_registered": total_registered,
            "total_hits": total_hits,
            "global_hit_rate": round(hit_rate, 3),
            "by_source": {k: {"registered": v["registered"], "hits": v["hits"],
                             "hit_rate": round(v["hits"] / v["registered"], 3) if v["registered"] > 0 else 0.0}
                        for k, v in source_stats.items()},
        }

    def reset(self) -> None:
        """重置所有数据"""
        self._registered.clear()
        self._hits.clear()
        self._query_stats.clear()
