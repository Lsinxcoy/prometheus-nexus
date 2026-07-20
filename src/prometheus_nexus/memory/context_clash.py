"""ContextClashDetector — 上下文冲突检测.

基于:
- "Context Switching Cost Analysis" (Kahn & Treem, 1984)
  - 冲突检测: 识别互斥上下文
  - 冲突类型: 语义/时间/角色/目标
  - 严重度评估: 低/中/高/紧急
  - 解决建议: 自动推荐冲突解决策略

算法:
    detect(contexts):
        1. 对每对上下文进行冲突分析
        2. 检查语义冲突(目标矛盾)
        3. 检查时间冲突(同时要求不同任务)
        4. 检查角色冲突(互斥角色)
        5. 返回冲突列表

复杂度:
    detect(): O(C^2) 其中C=上下文数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
from typing import Optional


# 互斥上下文对
MUTUALLY_EXCLUSIVE = {
    ("read_only", "write_mode"),
    ("development", "production"),
    ("testing", "production"),
    ("debug", "release"),
    ("training", "inference"),
    ("offline", "online"),
    ("draft", "final"),
    ("local", "remote"),
}


class ContextClashDetector:
    """上下文冲突检测 — 识别和处理互斥上下文.
    
    检测多个上下文之间的冲突并提供解决建议.
    """
    
    CONFLICT_TYPES = {
        "semantic": "语义冲突 — 目标或意图矛盾",
        "temporal": "时间冲突 — 同时期要求不同状态",
        "role": "角色冲突 — 互斥角色或模式",
        "goal": "目标冲突 — 优化目标不一致",
    }
    
    def __init__(self, exclusivity_pairs: Optional[set[tuple]] = None):
        """初始化.
        
        Args:
            exclusivity_pairs: 互斥对集合
        """
        self._exclusives = exclusivity_pairs or MUTUALLY_EXCLUSIVE
        self._conflicts: list[dict] = []
        self._total_checks = 0
    
    def detect(self, contexts: list[dict]) -> list[dict]:
        """检测上下文冲突.
        
        Args:
            contexts: 上下文列表 [{name, mode, role, goal, timestamp}]
        
        Returns:
            list: 冲突列表
        """
        self._total_checks += 1
        conflicts = []
        
        for i in range(len(contexts)):
            for j in range(i + 1, len(contexts)):
                a = contexts[i]
                b = contexts[j]
                
                pair_conflicts = self._analyze_pair(a, b)
                conflicts.extend(pair_conflicts)
        
        if conflicts:
            self._conflicts.extend(conflicts)
            if len(self._conflicts) > 500:
                self._conflicts = self._conflicts[-250:]
        
        return conflicts
    
    def _analyze_pair(self, a: dict, b: dict) -> list[dict]:
        """分析一对上下文.
        
        Args:
            a: 上下文A
            b: 上下文B
        
        Returns:
            list: 发现的冲突
        """
        conflicts = []
        
        # 1. 模式互斥检查
        mode_a = a.get("mode", "")
        mode_b = b.get("mode", "")
        if (mode_a, mode_b) in self._exclusives or (mode_b, mode_a) in self._exclusives:
            conflicts.append({
                "type": "role",
                "severity": self._calc_severity(a, b, "role"),
                "context_a": a.get("name", "unknown"),
                "context_b": b.get("name", "unknown"),
                "detail": f"互斥模式: {mode_a} vs {mode_b}",
                "resolution": self._suggest_resolution("role", mode_a, mode_b),
                "timestamp": time.time(),
            })
        
        # 2. 目标冲突检查
        goal_a = a.get("goal", "")
        goal_b = b.get("goal", "")
        if goal_a and goal_b and self._goals_conflict(goal_a, goal_b):
            conflicts.append({
                "type": "goal",
                "severity": self._calc_severity(a, b, "goal"),
                "context_a": a.get("name", "unknown"),
                "context_b": b.get("name", "unknown"),
                "detail": f"目标冲突: {goal_a[:50]} vs {goal_b[:50]}",
                "resolution": self._suggest_resolution("goal", goal_a, goal_b),
                "timestamp": time.time(),
            })
        
        # 3. 时间冲突检查
        ts_a = a.get("timestamp", 0)
        ts_b = b.get("timestamp", 0)
        if ts_a and ts_b and abs(ts_a - ts_b) < 5:
            if mode_a != mode_b and a.get("priority", 0) > 0.5 and b.get("priority", 0) > 0.5:
                conflicts.append({
                    "type": "temporal",
                    "severity": self._calc_severity(a, b, "temporal"),
                    "context_a": a.get("name", "unknown"),
                    "context_b": b.get("name", "unknown"),
                    "detail": "时间重叠且模式不同",
                    "resolution": self._suggest_resolution("temporal", None, None),
                    "timestamp": time.time(),
                })
        
        # 4. 语义冲突检查
        intent_a = a.get("intent", "")
        intent_b = b.get("intent", "")
        if intent_a and intent_b:
            antonyms = {"create": "delete", "start": "stop", "add": "remove",
                        "enable": "disable", "open": "close", "increase": "decrease"}
            if (intent_a.lower() in antonyms and antonyms.get(intent_a.lower()) == intent_b.lower()) or \
               (intent_b.lower() in antonyms and antonyms.get(intent_b.lower()) == intent_a.lower()):
                conflicts.append({
                    "type": "semantic",
                    "severity": "high",
                    "context_a": a.get("name", "unknown"),
                    "context_b": b.get("name", "unknown"),
                    "detail": f"语义对立: {intent_a} vs {intent_b}",
                    "resolution": self._suggest_resolution("semantic", intent_a, intent_b),
                    "timestamp": time.time(),
                })
        
        return conflicts
    
    def _goals_conflict(self, goal_a: str, goal_b: str) -> bool:
        """检查目标是否冲突.
        
        Args:
            goal_a: 目标A
            goal_b: 目标B
        
        Returns:
            bool: 是否冲突
        """
        conflict_keywords = {
            "minimize": "maximize",
            "fast": "accurate",
            "simple": "comprehensive",
            "static": "adaptive",
            "deterministic": "stochastic",
        }
        ga = goal_a.lower()
        gb = goal_b.lower()
        for k, v in conflict_keywords.items():
            if k in ga and v in gb:
                return True
        return False
    
    def _calc_severity(self, a: dict, b: dict, conflict_type: str) -> str:
        """计算冲突严重度.
        
        Args:
            a: 上下文A
            b: 上下文B
            conflict_type: 冲突类型
        
        Returns:
            str: 严重度
        """
        priority_sum = a.get("priority", 0) + b.get("priority", 0)
        
        if conflict_type == "semantic":
            return "high"
        elif conflict_type == "role":
            return "critical" if priority_sum > 1.5 else "high"
        elif priority_sum > 1.5:
            return "high"
        elif priority_sum > 0.8:
            return "medium"
        return "low"
    
    def _suggest_resolution(self, conflict_type: str, val_a, val_b) -> str:
        """生成解决建议.
        
        Args:
            conflict_type: 冲突类型
            val_a: 值A
            val_b: 值B
        
        Returns:
            str: 解决建议
        """
        resolutions = {
            "semantic": "按优先级顺序执行对立操作",
            "temporal": "串行化处理或拆分时间窗口",
            "role": f"保留{val_a}模式,延迟{val_b}上下文",
            "goal": "寻找Pareto最优折中方案",
        }
        return resolutions.get(conflict_type, "人工介入决策")
    
    def get_stats(self) -> dict:
        """���取统计."""
        type_counts = {}
        severity_counts = {}
        for c in self._conflicts:
            t = c.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
            s = c.get("severity", "unknown")
            severity_counts[s] = severity_counts.get(s, 0) + 1
        
        return {
            "total_checks": self._total_checks,
            "total_conflicts": len(self._conflicts),
            "conflict_types": type_counts,
            "severity_distribution": severity_counts,
        }
