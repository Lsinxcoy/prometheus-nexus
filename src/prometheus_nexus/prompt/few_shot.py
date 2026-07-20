"""FewShotSelector — Few-shot示例选择器.

基于:
- "Similarity-Based Example Selection for Few-Shot Learning"
  - 余弦相似度: 选择与查询最相似的示例
  - 多样性采样: 避免选择过于相似的示例
  - 池管理: 维护示例库
  - 动态更新: 根据反馈更新示例权重

算法:
    select(query, pool, k):
        1. 计算查询与每个示例的相似度
        2. 选择Top-K最相似示例
        3. 应用多样性过滤
        4. 返回选中示例

复杂度:
    select(): O(N×D) N=池大小,D=特征维度
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import math
import time
from collections import defaultdict


class FewShotSelector:
    """Few-shot示例选择器 — 基于相似度检索最佳示例.
    
    从示例池中选择与当前查询最相关且多样化的示例.
    """
    
    def __init__(self, max_pool_size: int = 1000):
        """初始化.
        
        Args:
            max_pool_size: 最大池大小
        """
        self._max_pool_size = max_pool_size
        self._pool: list[dict] = []
        self._usage_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "success": 0})
    
    def add_example(self, example_id: str, text: str, tags: list[str] | None = None,
                    features: list[float] | None = None) -> None:
        """添加示例到池.
        
        Args:
            example_id: 示例ID
            text: 示例文本
            tags: 标签列表
            features: 特征向量
        """
        entry = {
            "id": example_id,
            "text": text,
            "tags": set(tags or []),
            "features": features or self._extract_features(text),
            "added_at": time.time(),
        }
        
        self._pool.append(entry)
        
        # 限制池大小
        if len(self._pool) > self._max_pool_size:
            self._pool = self._pool[-self._max_pool_size // 2:]
    
    def select(self, query: str, k: int = 3, diversity: float = 0.3) -> list[dict]:
        """选择示例.
        
        Args:
            query: 查询文本
            k: 选择数量
            diversity: 多样性权重 [0, 1]
        
        Returns:
            list: 选中示例
        """
        if not self._pool:
            return []
        
        query_features = self._extract_features(query)
        
        # 1. 计算相似度
        scored = []
        for example in self._pool:
            sim = self._cosine_similarity(query_features, example["features"])
            
            # 标签匹配奖励
            query_tags = set(self._extract_tags(query))
            tag_overlap = len(query_tags & example["tags"]) / max(len(query_tags | example["tags"]), 1)
            
            # 综合得分
            combined = sim * (1 - diversity) + tag_overlap * diversity
            scored.append((example, combined))
        
        # 2. 按得分排序
        scored.sort(key=lambda x: x[1], reverse=True)
        
        # 3. 多样性过滤
        selected = []
        selected_texts = []
        
        for example, score in scored:
            if len(selected) >= k:
                break
            
            # 检查与已选示例的相似度
            is_diverse = True
            for sel_text in selected_texts:
                if self._text_similarity(example["text"], sel_text) > 0.8:
                    is_diverse = False
                    break
            
            if is_diverse:
                selected.append({
                    "id": example["id"],
                    "text": example["text"],
                    "similarity": round(score, 4),
                })
                selected_texts.append(example["text"])
                self._usage_stats[example["id"]]["count"] += 1
        
        return selected
    
    def record_feedback(self, example_id: str, success: bool) -> None:
        """记录反馈.
        
        Args:
            example_id: 示例ID
            success: 是否成功
        """
        stats = self._usage_stats[example_id]
        stats["count"] += 1
        if success:
            stats["success"] += 1
    
    def _extract_features(self, text: str) -> list[float]:
        """提取简单特征(词频向量).
        
        Args:
            text: 文本
        
        Returns:
            list: 特征向量
        """
        words = text.lower().split()
        
        # 简单特征: 长度, 平均词长, 大写字母比例, 标点比例
        features = [
            len(words),
            sum(len(w) for w in words) / max(len(words), 1),
            sum(1 for c in text if c.isupper()) / max(len(text), 1),
            sum(1 for c in text if c in '.,!?;:') / max(len(text), 1),
            len(set(words)) / max(len(words), 1),  # 词唯一性
        ]
        
        # 归一化
        magnitude = math.sqrt(sum(f * f for f in features)) or 1.0
        return [f / magnitude for f in features]
    
    def _extract_tags(self, text: str) -> list[str]:
        """提取标签.
        
        Args:
            text: 文本
        
        Returns:
            list: 标签列表
        """
        keywords = ["error", "debug", "test", "fix", "config", "deploy", "api", "data"]
        text_lower = text.lower()
        return [kw for kw in keywords if kw in text_lower]
    
    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """计算余弦相似度.
        
        Args:
            a: 向量A
            b: 向量B
        
        Returns:
            float: 相似度 [0, 1]
        """
        if len(a) != len(b):
            return 0.0
        
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        
        if mag_a == 0 or mag_b == 0:
            return 0.0
        
        return max(0, min(1, dot / (mag_a * mag_b)))
    
    def _text_similarity(self, a: str, b: str) -> float:
        """计算文本Jaccard相似度.
        
        Args:
            a: 文本A
            b: 文本B
        
        Returns:
            float: 相似度
        """
        set_a = set(a.lower().split())
        set_b = set(b.lower().split())
        
        if not set_a and not set_b:
            return 1.0
        
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        
        return intersection / max(union, 1)
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "pool_size": len(self._pool),
            "total_usage": sum(s["count"] for s in self._usage_stats.values()),
            "total_success": sum(s["success"] for s in self._usage_stats.values()),
        }

# 兼容别名
DynamicFewShot = FewShotSelector
