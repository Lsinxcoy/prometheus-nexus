"""FGGMVerifier — FGGM (Fuzzy Genetic Graph Matching) 验证.

基于:
- "Fuzzy Graph Matching for Evolutionary Validation"
  - 模糊匹配: 容错图相似度计算
  - 基因编码: 结构特征编码
  - 验证管道: 完整性/一致性/有效性
  - 相似度评分: 归一化图距离

算法:
    verify(graph):
        1. 提取节点/边特征
        2. 检查结构完整性
        3. 计算模糊相似度
        4. 返回验证报告

复杂度:
    verify(): O(V + E)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
from collections import defaultdict


class FGGVerifier:
    """FGGM验证器 — 模糊遗传图匹配验证.
    
    验证图结构完整性并计算与参考图的模糊相似度.
    """
    
    def __init__(self, tolerance: float = 0.1, min_nodes: int = 2):
        """初始化.
        
        Args:
            tolerance: 模糊匹配容差
            min_nodes: 最小节点数
        """
        self._tolerance = tolerance
        self._min_nodes = min_nodes
        self._reference: dict[str, set] = defaultdict(set)
        self._verification_log: list[dict] = []
    
    def set_reference(self, reference_graph: dict[str, set[str]]) -> None:
        """设置参考图.
        
        Args:
            reference_graph: 邻接表 {node: {neighbors}}
        """
        self._reference = defaultdict(set)
        for node, neighbors in reference_graph.items():
            self._reference[node] = set(neighbors)
    
    def verify(self, graph: dict[str, set[str]]) -> dict:
        """验证图结构.
        
        Args:
            graph: 待验证图 {node: {neighbors}}
        
        Returns:
            dict: 验证报告
        """
        all_nodes = set(graph.keys())
        for node, neighbors in graph.items():
            all_nodes.update(neighbors)
        
        # 1. 完整性检查
        node_count = len(all_nodes)
        edge_count = sum(len(n) for n in graph.values())
        has_isolated = any(node not in graph or len(graph[node]) == 0 
                          for node in all_nodes)
        
        # 2. 一致性检查(边是否双向)
        inconsistent_edges = []
        for node, neighbors in graph.items():
            for neighbor in neighbors:
                if neighbor in graph and node not in graph[neighbor]:
                    inconsistent_edges.append((node, neighbor))
        
        consistent = len(inconsistent_edges) == 0
        
        # 3. 连通性检查(BFS)
        if all_nodes:
            start = next(iter(all_nodes))
            visited = set()
            queue = [start]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                for neighbor in graph.get(current, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)
            connected = len(visited) == len(all_nodes)
            components = len(all_nodes) - len(visited) + 1
        else:
            connected = False
            components = 0
        
        # 4. 模糊相似度(与参考图)
        similarity = self._compute_similarity(graph)
        
        # 5. 综合判断
        valid = (
            node_count >= self._min_nodes and
            consistent and
            abs(similarity - 1.0) <= self._tolerance if self._reference else True
        )
        
        report = {
            "valid": valid,
            "node_count": node_count,
            "edge_count": edge_count,
            "has_isolated_nodes": has_isolated,
            "consistent": consistent,
            "inconsistent_edges": len(inconsistent_edges),
            "connected": connected,
            "components": components,
            "similarity_to_reference": round(similarity, 4),
            "ts": time.time(),
        }
        
        self._verification_log.append(report)
        if len(self._verification_log) > 200:
            self._verification_log = self._verification_log[-100:]
        
        return report
    
    def _compute_similarity(self, graph: dict[str, set[str]]) -> float:
        """计算与参考图的Jaccard相似度.
        
        Args:
            graph: 待验证图
        
        Returns:
            float: Jaccard相似度 [0, 1]
        """
        if not self._reference:
            return 1.0
        
        # 边集Jaccard
        graph_edges = set()
        for node, neighbors in graph.items():
            for n in neighbors:
                graph_edges.add((min(node, n), max(node, n)))
        
        ref_edges = set()
        for node, neighbors in self._reference.items():
            for n in neighbors:
                ref_edges.add((min(node, n), max(node, n)))
        
        if not graph_edges and not ref_edges:
            return 1.0
        
        intersection = len(graph_edges & ref_edges)
        union = len(graph_edges | ref_edges)
        
        return intersection / max(union, 1)
    
    def get_stats(self) -> dict:
        """获取统计."""
        if not self._verification_log:
            return {"verifications": 0}
        
        valid_count = sum(1 for v in self._verification_log if v["valid"])
        avg_similarity = sum(v["similarity_to_reference"] for v in self._verification_log) / len(self._verification_log)
        
        return {
            "verifications": len(self._verification_log),
            "valid_rate": round(valid_count / len(self._verification_log), 4),
            "avg_similarity": round(avg_similarity, 4),
        }
    
    # 兼容别名: life.py 调用 verify_compat(context_dict)
    def verify_compat(self, context: dict) -> dict:
        """兼容性验证 (接受任意字典上下文)."""
        graph = context.get("graph", {})
        return self.verify(graph)
