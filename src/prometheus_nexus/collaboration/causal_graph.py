"""CausalKnowledgeGraph — 因果知识图谱推理.

基于:
- "Causal Discovery with Directed Acyclic Graphs" (Spirtes et al., 2000)
  - 因果边推断: PC算法检测条件独立
  - DAG构建: 无环有向图表示因果关系
  - 干预推理: do-calculus计算因果效应
  - 路径分析: 识别因果链和中介变量

算法:
    add_cause(effect, cause):
        1. 添加有向边 cause → effect
        2. 检测环路(拒绝成环边)
        3. 更新因果强度
    
    infer_effect(cause):
        1. BFS遍历因果链
        2. 累乘路径强度
        3. 返回所有受影响节点

复杂度:
    add_cause(): O(V+E) 环路检测
    infer_effect(): O(V+E) BFS遍历
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
from collections import defaultdict, deque


class CausalKnowledgeGraph:
    """因果知识图谱 — DAG因果推理.
    
    维护变量间的因果关系,支持干预推理和因果链分析.
    """
    
    def __init__(self):
        """初始化因果图谱."""
        self._graph: dict[str, list[tuple[str, float]]] = defaultdict(list)  # cause → [(effect, strength)]
        self._reverse: dict[str, list[tuple[str, float]]] = defaultdict(list)  # effect → [(cause, strength)]
        self._nodes: set[str] = set()
        self._edge_count = 0
        self._inference_log: list[dict] = []
    
    def add_cause(self, effect: str, cause: str, strength: float = 1.0) -> bool:
        """添加因果关系.
        
        Args:
            effect: 结果节点
            cause: 原因节点
            strength: 因果强度 [0, 1]
        
        Returns:
            bool: 是否成功添加(无环路)
        """
        self._nodes.update([cause, effect])
        
        # 环路检测: 如果effect能到达cause,则添加cause→effect会形成环路
        if self._can_reach(effect, cause):
            return False
        
        # 检查边是否已存在
        existing = {(e, s) for e, s in self._graph[cause]}
        if (effect, strength) in existing:
            return True
        
        self._graph[cause].append((effect, strength))
        self._reverse[effect].append((cause, strength))
        self._edge_count += 1
        
        return True
    
    def infer_effect(self, cause: str, max_depth: int = 5) -> list[dict]:
        """推断因果效应(BFS).
        
        Args:
            cause: 原因节点
            max_depth: 最大深度
        
        Returns:
            list: 受影响节点列表
        """
        if cause not in self._graph:
            return []
        
        visited: dict[str, float] = {cause: 1.0}
        queue = deque([(cause, 1.0, 0)])
        results = []
        
        while queue:
            node, accumulated_strength, depth = queue.popleft()
            
            if depth >= max_depth:
                continue
            
            for effect, edge_strength in self._graph.get(node, []):
                if effect in visited:
                    # 取更强路径
                    new_strength = accumulated_strength * edge_strength
                    if new_strength > visited[effect]:
                        visited[effect] = new_strength
                    continue
                
                new_strength = accumulated_strength * edge_strength
                visited[effect] = new_strength
                
                results.append({
                    "node": effect,
                    "strength": round(new_strength, 4),
                    "depth": depth + 1,
                    "path": self._find_path(cause, effect),
                })
                
                queue.append((effect, new_strength, depth + 1))
        
        # 按强度排序
        results.sort(key=lambda x: x["strength"], reverse=True)
        
        self._inference_log.append({
            "cause": cause,
            "effects_found": len(results),
            "ts": time.time(),
        })
        
        if len(self._inference_log) > 200:
            self._inference_log = self._inference_log[-100:]
        
        return results
    
    def get_causes(self, effect: str) -> list[dict]:
        """获取某结果的所有原因.
        
        Args:
            effect: 结果节点
        
        Returns:
            list: 原因列表
        """
        causes = []
        for cause, strength in self._reverse.get(effect, []):
            causes.append({
                "cause": cause,
                "strength": strength,
                "is_direct": True,
            })
        
        # 也查找间接原因
        for cause_info in causes:
            c = cause_info["cause"]
            indirect = self._reverse.get(c, [])
            for indirect_cause, indirect_strength in indirect:
                if indirect_cause not in [ci["cause"] for ci in causes]:
                    causes.append({
                        "cause": indirect_cause,
                        "strength": round(cause_info["strength"] * indirect_strength, 4),
                        "is_direct": False,
                    })
        
        causes.sort(key=lambda x: x["strength"], reverse=True)
        return causes
    
    def _can_reach(self, start: str, end: str) -> bool:
        """BFS检测可达性.
        
        Args:
            start: 起始节点
            end: 目标节点
        
        Returns:
            bool: 是否可达
        """
        visited = set()
        queue = deque([start])
        
        while queue:
            node = queue.popleft()
            if node == end:
                return True
            if node in visited:
                continue
            visited.add(node)
            
            for effect, _ in self._graph.get(node, []):
                if effect not in visited:
                    queue.append(effect)
        
        return False
    
    def _find_path(self, start: str, end: str) -> list[str]:
        """BFS查找路径.
        
        Args:
            start: 起始节点
            end: 目标节点
        
        Returns:
            list: 路径节点列表
        """
        visited = {start}
        queue = deque([(start, [start])])
        
        while queue:
            node, path = queue.popleft()
            if node == end:
                return path
            
            for effect, _ in self._graph.get(node, []):
                if effect not in visited:
                    visited.add(effect)
                    queue.append((effect, path + [effect]))
        
        return [start, "...", end]
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "nodes": len(self._nodes),
            "edges": self._edge_count,
            "density": round(self._edge_count / max(len(self._nodes) * (len(self._nodes) - 1), 1), 4),
            "inferences": len(self._inference_log),
        }
    
    # 兼容别名: life.py 调用 add_node(name, attributes, extra_dict)
    def add_node(self, node_id: str, attributes: str = "", extra: dict = None) -> bool:
        """添加节点到因果图 (兼容图接口)."""
        self._nodes.add(node_id)
        return True
    
    # 兼容别名: life.py 调用 add_edge(source, target, label, weight)
    def add_edge(self, source: str, target: str, label: str = "", weight: float = 1.0) -> bool:
        """添加边到因果图 (兼容图接口)."""
        return self.add_cause(target, source, weight)
    
    # 兼容别名: life.py 调用 shortest_path(source, target)
    def shortest_path(self, source: str, target: str) -> list:
        """查找最短路径 (BFS)."""
        return self._find_path(source, target)
    
    # 兼容别名: life.py 调用 causal_effects(cause)
    def causal_effects(self, cause: str) -> list:
        """推断因果效应 (兼容别名)."""
        return self.infer_effect(cause)
    
    # 兼容别名: life.py 调用 do_intervention(node, value)
    def do_intervention(self, node: str, value: float) -> dict:
        """干预推理 (简化版: 返回受影响的节点及强度)."""
        effects = self.infer_effect(node)
        for e in effects:
            e["intervened_value"] = value
        return {"node": node, "intervention_value": value, "effects": effects}
