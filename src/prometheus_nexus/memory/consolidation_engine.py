"""ConsolidationEngine — 记忆整合引擎.

基于:
- "Memory Consolidation during Sleep" (Diekelmann & Born, 2010)
  - 系统整合: 海马体 → 新皮层
  - 选择性巩固: 高价值记忆优先
  - 去整合: 消除冗余/冲突记忆

算法:
    consolidate(memories):
        1. 按时间窗分组
        2. 相似度合并
        3. 重要性排序
        4. 冲突解决
        5. 输出整合结果

复杂度:
    consolidate(): O(N log N) 其中 N = 记忆数量
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
import re
from dataclasses import dataclass, field


@dataclass
class ConsolidationResult:
    """整合结果."""
    merged_count: int = 0
    pruned_count: int = 0
    promoted_count: int = 0
    conflicts_resolved: int = 0
    groups: list[dict] = field(default_factory=list)
    kept: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0


class ConsolidationEngine:
    """记忆整合引擎.
    
    三阶段: 分组 → 合并 → 清理
    """
    
    def __init__(self, similarity_threshold: float = 0.85, min_importance: float = 0.3):
        self.similarity_threshold = similarity_threshold
        self.min_importance = min_importance
        self._history: list[ConsolidationResult] = []
        self._buffer: list[dict] = []
    
    def add(self, memory: dict) -> None:
        """添加待整合记忆."""
        self._buffer.append({
            "id": memory.get("id", ""),
            "content": memory.get("content", ""),
            "importance": memory.get("importance", 0.5),
            "timestamp": memory.get("timestamp", time.time()),
            "tags": memory.get("tags", []),
        })
    
    def consolidate(self, memories: list[dict] | None = None) -> ConsolidationResult:
        """执行整合流程."""
        start = time.time()
        result = ConsolidationResult()
        
        items = memories if memories is not None else self._buffer
        if not items:
            self._history.append(result)
            return result
        
        # 阶段1: 按相似度分组
        groups = self._group_by_similarity(items)
        result.groups = [
            {"count": len(g), "avg_importance": sum(m["importance"] for m in g) / len(g)}
            for g in groups
        ]
        
        # 阶段2: 合并相似记忆
        kept: list[dict] = []
        for group in groups:
            if len(group) == 1:
                kept.append(group[0])
            else:
                # 按重要性排序，保留最好的
                group.sort(key=lambda m: m["importance"], reverse=True)
                kept.append(group[0])
                result.merged_count += len(group) - 1
                # 提升保留项的重要性
                group[0]["importance"] = min(1.0, group[0]["importance"] * (1 + 0.1 * len(group)))
        
        # 阶段3: 解决冲突
        conflicts = self._resolve_conflicts(kept)
        result.conflicts_resolved = len(conflicts)
        
        # 阶段4: 清理低重要性记忆
        before_count = len(conflicts)
        conflicts = [m for m in conflicts if m["importance"] >= self.min_importance]
        result.pruned_count = before_count - len(conflicts)
        result.promoted_count = len(conflicts)

        # 保留整合结果: 整合后的去重/剪枝记忆集必须留存, 否则"合并/清理"两阶段
        # 形同虚设(记忆被静默丢弃)。显式传入 memories 时把整合集存入 result.kept
        # 供调用方持久化; 默认(内部缓冲区)路径写回 self._buffer 而非整体清空(数据丢失)。
        result.kept = conflicts
        if memories is None:
            self._buffer = conflicts

        result.duration_ms = (time.time() - start) * 1000
        self._history.append(result)
        return result

    def run(self, memories: list[dict] | None = None) -> dict:
        """运行整合（兼容API）。"""
        result = self.consolidate(memories)
        return {
            "status": "success",
            "merged": result.merged_count,
            "pruned": result.pruned_count,
            "promoted": result.promoted_count,
            "conflicts_resolved": result.conflicts_resolved,
            "kept": len(result.kept),
            "duration_ms": result.duration_ms,
        }
    
    def _group_by_similarity(self, items: list[dict]) -> list[list[dict]]:
        """基于关键词重叠度分组."""
        if not items:
            return []
        
        def keyword_overlap(a: dict, b: dict) -> float:
            words_a = set(re.findall(r'\b\w+\b', a.get("content", "").lower()))
            words_b = set(re.findall(r'\b\w+\b', b.get("content", "").lower()))
            if not words_a or not words_b:
                return 0.0
            return len(words_a & words_b) / min(len(words_a), len(words_b))
        
        groups: list[list[dict]] = []
        used = [False] * len(items)
        
        for i in range(len(items)):
            if used[i]:
                continue
            group = [items[i]]
            used[i] = True
            for j in range(i + 1, len(items)):
                if not used[j] and keyword_overlap(items[i], items[j]) >= self.similarity_threshold:
                    group.append(items[j])
                    used[j] = True
            groups.append(group)
        
        return groups
    
    def _resolve_conflicts(self, items: list[dict]) -> list[dict]:
        """解决冲突记忆."""
        # 按时间戳排序，保留最新的
        items.sort(key=lambda m: m.get("timestamp", 0), reverse=True)
        return items
    
    def get_stats(self) -> dict:
        """获取整合统计."""
        total_merged = sum(r.merged_count for r in self._history)
        total_pruned = sum(r.pruned_count for r in self._history)
        
        return {
            "runs": len(self._history),
            "total_merged": total_merged,
            "total_pruned": total_pruned,
            "total_conflicts": sum(r.conflicts_resolved for r in self._history),
            "buffer_size": len(self._buffer),
        }
