"""MARS — Memory-Augmented Reasoning System.

基于:
- "Bayesian Belief Tracking with Confidence Decay"
  - 信念更新: 贝叶斯更新置信度
  - 衰减机制: 时间衰减降低旧信念
  - 一致性检查: 检测矛盾信念
  - 证据聚合: 多证据源综合评估

算法:
    update_belief(name, evidence, prior):
        1. 计算似然比
        2. 贝叶斯更新置信度
        3. 应用时间衰减
        4. 检查矛盾

复杂度:
    update_belief(): O(1), check_consistency(): O(B^2) 其中B=信念数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import math


class MARS:
    """记忆增强推理系统 — 信念追踪.
    
    管理信念库,支持贝叶斯更新和一致性检查.
    """
    
    def __init__(self, decay_rate: float = 0.001, contradiction_threshold: float = 0.8):
        """初始化.
        
        Args:
            decay_rate: 时间衰减率(每秒)
            contradiction_threshold: 矛盾阈值
        """
        self._decay_rate = decay_rate
        self._contradiction_threshold = contradiction_threshold
        
        self._beliefs: dict[str, dict] = {}
        self._evidence_history: list[dict] = []
        self._update_log: list[dict] = []
    
    def create_belief(self, name: str, content: str, confidence: float = 0.5,
                      tags: list[str] | None = None) -> dict:
        """创建信念.
        
        Args:
            name: 信念名称
            content: 信念内容
            confidence: 初始置信度 [0, 1]
            tags: 标签列表
        
        Returns:
            dict: 信念信息
        """
        belief = {
            "name": name,
            "content": content,
            "confidence": max(0.0, min(1.0, confidence)),
            "tags": tags or [],
            "updates": 0,
            "created_at": time.time(),
            "last_updated": time.time(),
            "evidence": [],
        }
        self._beliefs[name] = belief
        return dict(belief)
    
    def update_belief(self, name: str, evidence: dict | float | None = None,
                      new_confidence: float | None = None) -> dict | None:
        """更新信念.
        
        使用贝叶斯更新或直接设置.
        
        Args:
            name: 信念名称
            evidence: 证据 ({likelihood: float, direction: 'support'/'refute'}) 或直接置信度(float)
            new_confidence: 直接设置置信度(覆盖证据)
        
        Returns:
            dict: 更新后的信念或None
        """
        if name not in self._beliefs:
            return None
        
        belief = self._beliefs[name]
        now = time.time()
        
        # 时间衰减
        elapsed = now - belief["last_updated"]
        decay = math.exp(-self._decay_rate * elapsed)
        prior = belief["confidence"] * decay
        
        if isinstance(evidence, float):
            # 兼容旧版: update_belief(name, confidence) — 直接设置置信度
            updated_confidence = max(0.0, min(1.0, evidence))
        elif new_confidence is not None:
            # 直接设置
            updated_confidence = max(0.0, min(1.0, new_confidence))
        elif evidence:
            # 贝叶斯更新
            likelihood = evidence.get("likelihood", 1.0)
            direction = evidence.get("direction", "support")
            
            if direction == "support":
                # 加强信念
                updated_confidence = prior + (1 - prior) * likelihood * 0.5
            else:
                # 削弱信念
                updated_confidence = prior * (1 - likelihood * 0.5)
            
            updated_confidence = max(0.0, min(1.0, updated_confidence))
            
            # 记录证据
            belief["evidence"].append({
                "likelihood": likelihood,
                "direction": direction,
                "ts": now,
            })
        else:
            updated_confidence = prior
        
        # 更新信念
        belief["confidence"] = updated_confidence
        belief["updates"] += 1
        belief["last_updated"] = now
        
        self._update_log.append({
            "name": name,
            "old_confidence": round(prior, 4),
            "new_confidence": round(updated_confidence, 4),
            "ts": now,
        })
        
        return dict(belief)
    
    def get_belief(self, name: str) -> dict | None:
        """获取信念.
        
        Args:
            name: 信念名称
        
        Returns:
            dict: 信念信息或None
        """
        if name not in self._beliefs:
            return None
        
        belief = self._beliefs[name]
        result = dict(belief)
        
        # 应用时间衰减到返回值
        now = time.time()
        elapsed = now - belief["last_updated"]
        decay = math.exp(-self._decay_rate * elapsed)
        result["current_confidence"] = round(belief["confidence"] * decay, 4)
        result["decay_factor"] = round(decay, 4)
        
        return result
    
    def check_consistency(self) -> list[dict]:
        """检查信念一致性.
        
        检测标签相同但置信度方向相反的信念.
        
        Returns:
            list: 矛盾列表
        """
        contradictions = []
        belief_list = list(self._beliefs.values())
        
        for i in range(len(belief_list)):
            for j in range(i + 1, len(belief_list)):
                a = belief_list[i]
                b = belief_list[j]
                
                # 检查标签交集
                common_tags = set(a.get("tags", [])) & set(b.get("tags", []))
                if not common_tags:
                    continue
                
                # 检查置信度矛盾 (一个高一个低)
                conf_a = a["confidence"]
                conf_b = b["confidence"]
                
                if (conf_a > self._contradiction_threshold and 
                    conf_b < (1 - self._contradiction_threshold)):
                    contradictions.append({
                        "belief_a": a["name"],
                        "belief_b": b["name"],
                        "confidence_a": round(conf_a, 4),
                        "confidence_b": round(conf_b, 4),
                        "common_tags": list(common_tags),
                        "severity": "high" if abs(conf_a - conf_b) > 0.7 else "medium",
                    })
        
        return contradictions
    
    def delete_belief(self, name: str) -> bool:
        """删除信念.
        
        Args:
            name: 信念名称
        
        Returns:
            bool: 是否成功
        """
        if name in self._beliefs:
            del self._beliefs[name]
            return True
        return False
    
    def get_high_confidence_beliefs(self, threshold: float = 0.8) -> list[dict]:
        """获取高置信度信念.
        
        Args:
            threshold: 置信度阈值
        
        Returns:
            list: 高置信度信念列表
        """
        return [
            dict(b) for b in self._beliefs.values()
            if b["confidence"] >= threshold
        ]
    
    def get_all_beliefs(self) -> list[dict]:
        """获取所有信念 (兼容 life.py 调用)."""
        return [dict(b) for b in self._beliefs.values()]
    
    def get_stats(self) -> dict:
        """获取统计."""
        confidences = [b["confidence"] for b in self._beliefs.values()]
        contradictions = self.check_consistency()
        
        return {
            "beliefs": len(self._beliefs),
            "avg_confidence": round(sum(confidences) / max(len(confidences), 1), 4),
            "total_updates": sum(b["updates"] for b in self._beliefs.values()),
            "contradictions": len(contradictions),
            "high_confidence": len(self.get_high_confidence_beliefs()),
            "update_log_entries": len(self._update_log),
        }
