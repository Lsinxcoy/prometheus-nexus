"""MultiHopRetriever — 多跳推理检索.

基于:
- "Multi-hop Retrieval-Augmented Generation" (FLewis et al., 2020)
  - 跳跃检索: 多轮迭代式知识发现
  - 桥接节点: 连接不同知识领域的中间实体
  - 路径评分: 综合跳数+相关度+置信度
  - 循环检测: 避免重复访问

算法:
    retrieve(query, max_hops):
        1. 首轮检索: 直接匹配查询
        2. 每跳: 从结果中提取关键词→扩展检索
        3. 合并去重: 合并所有跳跃结果
        4. 路径评分: 跳数越短权重越高

复杂度:
    retrieve(): O(H × K) 其中H=跳数,K=每跳结果数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
from collections import defaultdict


class MultiHopRetriever:
    """多跳推理检索 — 迭代式知识发现.
    
    通过多轮检索逐步深入知识图谱,发现间接关联.
    """
    
    def __init__(self, max_hops: int = 3, results_per_hop: int = 5,
                 hop_decay: float = 0.7):
        """初始化.
        
        Args:
            max_hops: 最大跳跃次数
            results_per_hop: 每跳最大结果数
            hop_decay: 跳数衰减因子
        """
        self._max_hops = max_hops
        self._results_per_hop = results_per_hop
        self._hop_decay = hop_decay
        
        # 知识库 (词→文档映射)
        self._knowledge_base: dict[str, list[dict]] = defaultdict(list)
        self._retrieval_log: list[dict] = []
        self._total_retrievals = 0
    
    def add_document(self, doc_id: str, content: str, keywords: list[str] | None = None):
        """添加文档到知识库.
        
        Args:
            doc_id: 文档ID
            content: 文档内容
            keywords: 关键词列表
        """
        words = set(content.lower().split()) if not keywords else set(keywords)
        doc_entry = {"id": doc_id, "content": content, "words": words, "ts": time.time()}
        
        for word in words:
            self._knowledge_base[word].append(doc_entry)
    
    def retrieve(self, query: str) -> list[dict]:
        """多跳检索.
        
        Args:
            query: 查询字符串
        
        Returns:
            list: 检索结果(带跳数信息)
        """
        self._total_retrievals += 1
        query_words = set(query.lower().split())
        all_results: dict[str, dict] = {}
        visited_words: set[str] = set()
        paths: list[dict] = []
        
        # 逐跳检索
        current_words = query_words.copy()
        
        for hop in range(self._max_hops):
            if not current_words:
                break
            
            hop_results = []
            next_words = set()
            
            for word in current_words:
                if word in visited_words:
                    continue
                
                visited_words.add(word)
                matches = self._knowledge_base.get(word, [])
                
                for match in matches[:self._results_per_hop]:
                    doc_id = match["id"]
                    if doc_id in all_results:
                        # 已有记录,更新跳数(取更短)
                        if hop < all_results[doc_id]["first_found_at_hop"]:
                            all_results[doc_id]["first_found_at_hop"] = hop
                    else:
                        # 新发现
                        all_results[doc_id] = {
                            "id": doc_id,
                            "content": match["content"][:200],
                            "first_found_at_hop": hop,
                            "bridge_words": list(query_words & match["words"]),
                            "score": 0.0,
                        }
                    
                    # 提取下一跳关键词
                    new_words = match["words"] - visited_words
                    next_words.update(new_words)
                    
                    hop_results.append({
                        "word": word,
                        "doc_id": doc_id,
                        "hop": hop,
                    })
            
            # 记录路径
            paths.append({
                "hop": hop,
                "queried_words": list(current_words),
                "results_found": len(hop_results),
            })
            
            # 选择下一跳的关键词(去重+限制数量)
            next_words -= visited_words
            current_words = set(list(next_words)[:self._results_per_hop])
        
        # 计算最终得分
        for doc_id, info in all_results.items():
            hop = info["first_found_at_hop"]
            hop_weight = self._hop_decay ** hop
            bridge_weight = min(1.0, len(info.get("bridge_words", [])) / 3)
            info["score"] = round(hop_weight * 0.7 + bridge_weight * 0.3, 4)
        
        # 排序返回
        sorted_results = sorted(all_results.values(), key=lambda x: x["score"], reverse=True)
        
        # 记录日志
        self._retrieval_log.append({
            "query": query[:100],
            "total_docs": len(sorted_results),
            "hops_used": len(paths),
            "unique_words": len(visited_words),
            "ts": time.time(),
        })
        
        if len(self._retrieval_log) > 500:
            self._retrieval_log = self._retrieval_log[-250:]
        
        return sorted_results
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "total_retrievals": self._total_retrievals,
            "knowledge_base_size": sum(len(v) for v in self._knowledge_base.values()),
            "unique_terms": len(self._knowledge_base),
            "max_hops": self._max_hops,
            "avg_results": (
                sum(len(r) for r in [self._retrieval_log[-10:]]) / max(len(self._retrieval_log[-10:]), 1)
                if self._retrieval_log else 0
            ),
        }
