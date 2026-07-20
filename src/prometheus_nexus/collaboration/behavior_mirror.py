"""BehaviorMirror — 行为镜像与学习.

基于:
- "Imitation Learning via Behavioral Cloning" (Piotrowski et al., 2015)
  - 行为记录: 追踪决策轨迹
  - 模式提取: 高频行为序列提取
  - 镜像学习: 模仿高绩效行为模式
  - 偏差检测: 识别偏离最佳实践

算法:
    record(behavior):
        1. 记录行为时间和特征
        2. 更新行为统计
    
    get_mirror():
        1. 统计行为频率分布
        2. 提取Top-K高频模式
        3. 计算置信度
        4. 返回推荐行为

复杂度:
    record(): O(1)
    get_mirror(): O(N log K) 其中N=行为数,K=模式数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
from collections import Counter, defaultdict


class BehaviorMirror:
    """行为镜像 — 通过观察历史行为提取最佳实践.
    
    记录行为轨迹，提取高频成功模式，为新决策提供参考.
    """
    
    def __init__(self, max_history: int = 1000, top_k: int = 5):
        """初始化.
        
        Args:
            max_history: 最大历史记录数
            top_k: 返回Top-K模式
        """
        self._max_history = max_history
        self._top_k = top_k
        self._history: list[dict] = []
        self._success_patterns: Counter = Counter()
        self._failure_patterns: Counter = Counter()
        self._behavior_counts: Counter = Counter()
        self._context_behavior: defaultdict = defaultdict(list)
    
    def record(self, action: str, context: str, success: bool = True,
               score: float = 1.0) -> None:
        """记录行为.
        
        Args:
            action: 行为动作
            context: 上下文标签
            success: 是否成功
            score: 绩效得分
        """
        entry = {
            "action": action,
            "context": context,
            "success": success,
            "score": score,
            "timestamp": time.time(),
        }
        self._history.append(entry)
        
        # 限制历史长度
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history // 2:]
        
        # 更新统计
        pattern_key = f"{context}:{action}"
        self._behavior_counts[action] += 1
        
        if success:
            self._success_patterns[pattern_key] += score
        else:
            self._failure_patterns[pattern_key] += 1
        
        # 上下文→行为映射
        self._context_behavior[context].append({
            "action": action,
            "success": success,
            "score": score,
        })
        
        # 限制上下文历史
        if len(self._context_behavior[context]) > 200:
            self._context_behavior[context] = self._context_behavior[context][-100:]
    
    def get_mirror(self, context: str, top_k: int | None = None) -> list[dict]:
        """获取行为镜像推荐.
        
        Args:
            context: 当前上下文
            top_k: 返回数量
        
        Returns:
            list: 推荐行为列表
        """
        k = top_k or self._top_k
        candidates = []
        
        # 1. 查找上下文相关行为
        context_behaviors = self._context_behavior.get(context, [])
        
        # 2. 计算每个动作的得分
        action_stats: dict[str, dict] = {}
        for beh in context_behaviors:
            a = beh["action"]
            if a not in action_stats:
                action_stats[a] = {"total": 0, "success": 0, "total_score": 0.0}
            action_stats[a]["total"] += 1
            if beh["success"]:
                action_stats[a]["success"] += 1
                action_stats[a]["total_score"] += beh["score"]
        
        # 3. 计算综合得分
        for action, stats in action_stats.items():
            success_rate = stats["success"] / max(stats["total"], 1)
            avg_score = stats["total_score"] / max(stats["success"], 1)
            frequency = self._behavior_counts.get(action, 0) / max(len(self._history), 1)
            
            # 综合得分: 成功率×0.5 + 平均得分×0.3 + 频率×0.2
            combined = success_rate * 0.5 + avg_score * 0.3 + min(frequency * 10, 1.0) * 0.2
            
            candidates.append({
                "action": action,
                "success_rate": round(success_rate, 4),
                "avg_score": round(avg_score, 4),
                "frequency": round(frequency, 4),
                "combined_score": round(combined, 4),
                "sample_count": stats["total"],
            })
        
        # 4. 排序返回Top-K
        candidates.sort(key=lambda x: x["combined_score"], reverse=True)
        return candidates[:k]
    
    def get_failure_patterns(self, top_k: int | None = None) -> list[dict]:
        """获取失败模式.
        
        Args:
            top_k: 返回数量
        
        Returns:
            list: 失败模式列表
        """
        k = top_k or self._top_k
        failures = [
            {"pattern": p, "count": c}
            for p, c in self._failure_patterns.most_common(k)
        ]
        return failures
    
    def get_stats(self) -> dict:
        """获取统计."""
        total = len(self._history)
        success_count = sum(1 for h in self._history if h["success"])
        
        return {
            "total_behaviors": total,
            "success_rate": round(success_count / max(total, 1), 4),
            "unique_actions": len(self._behavior_counts),
            "contexts_tracked": len(self._context_behavior),
            "success_patterns": len(self._success_patterns),
            "failure_patterns": len(self._failure_patterns),
        }
    
    # 兼容别名: test_stress.py / life.py 调用 mirror()
    def mirror(self, context: str, action: str = "", metadata: dict | None = None) -> list[dict]:
        """行为镜像推荐 (兼容别名)."""
        return self.get_mirror(context)
    
    def compute_profile(self, context: str) -> dict:
        """计算行为画像.
        
        Args:
            context: 上下文标签
        
        Returns:
            dict: 行为画像统计
        """
        behaviors = self._context_behavior.get(context, [])
        if not behaviors:
            return {"context": context, "total": 0, "actions": {}, "success_rate": 0.0}
        
        action_stats: dict[str, dict] = {}
        for beh in behaviors:
            a = beh["action"]
            if a not in action_stats:
                action_stats[a] = {"total": 0, "success": 0, "total_score": 0.0}
            action_stats[a]["total"] += 1
            if beh["success"]:
                action_stats[a]["success"] += 1
                action_stats[a]["total_score"] += beh["score"]
        
        # 计算成功率
        total_success = sum(1 for b in behaviors if b["success"])
        
        return {
            "context": context,
            "total": len(behaviors),
            "success_rate": round(total_success / max(len(behaviors), 1), 4),
            "unique_actions": len(action_stats),
            "actions": action_stats,
        }
    
    def detect_deviation(self, context: str) -> dict:
        """检测行为偏差.
        
        Args:
            context: 上下文标签
        
        Returns:
            dict: 偏差检测报告
        """
        behaviors = self._context_behavior.get(context, [])
        if len(behaviors) < 5:
            return {"context": context, "deviation": 0.0, "status": "insufficient_data", "sample_size": len(behaviors)}
        
        # 计算最近窗口与整体窗口的成功率差异
        recent = behaviors[-10:]
        overall_success = sum(1 for b in behaviors if b["success"]) / max(len(behaviors), 1)
        recent_success = sum(1 for b in recent if b["success"]) / max(len(recent), 1)
        
        deviation = abs(recent_success - overall_success)
        
        status = "normal"
        if deviation > 0.3:
            status = "significant_deviation"
        elif deviation > 0.15:
            status = "mild_deviation"
        
        return {
            "context": context,
            "deviation": round(deviation, 4),
            "overall_success_rate": round(overall_success, 4),
            "recent_success_rate": round(recent_success, 4),
            "status": status,
            "sample_size": len(behaviors),
        }
