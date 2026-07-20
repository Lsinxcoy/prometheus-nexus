"""RuleExpirationAudit — 规则生命周期管理.

基于:
- MiMo: "30天未触发→标记inert,规则过期审计"
  - TTL管理: 自动过期检测
  - 分级处理: 安全规则永不过期
  - 惯性检测: 长期未触发标记
  - 自动清理: 过期规则自动归档

算法:
    audit():
        1. 遍历所有规则
        2. 计算距上次触发天数
        3. 根据类型判断是否过期
        4. 标记/归档/删除

复杂度:
    audit(): O(R) 其中R=规则数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
from collections import defaultdict


class RuleExpirationAudit:
    """规则过期审计 — 分级TTL管理.
    
    安全规则永不过期,工程规则按TTL管理.
    """
    
    # 规则状态
    ACTIVE = "active"
    INERT = "inert"
    EXPIRED = "expired"
    ARCHIVED = "archived"
    
    def __init__(self, security_expires: bool = False, engineering_expiry_days: int = 30,
                 inert_threshold_days: int = 20, archive_after_expiry_days: int = 7):
        """初始化.
        
        Args:
            security_expires: 安全规则是否过期(默认否)
            engineering_expiry_days: 工程规则过期天数
            inert_threshold_days: 惰性标记天数
            archive_after_expiry_days: 过期后归档天数
        """
        self._security_expires = security_expires
        self._expiry_days = engineering_expiry_days
        self._inert_days = inert_threshold_days
        self._archive_days = archive_after_expiry_days
        
        self._rules: dict[str, dict] = {}
        self._archive: list[dict] = []
        self._audit_history: list[dict] = []
        self._trigger_counts: dict[str, int] = defaultdict(int)
    
    def register_rule(self, rule_id: str, rule_type: str = "engineering",
                      description: str = "", last_triggered: float = 0.0):
        """注册规则.
        
        Args:
            rule_id: 规则ID
            rule_type: 规则类型 (security/engineering)
            description: 描述
            last_triggered: 上次触发时间
        """
        self._rules[rule_id] = {
            "type": rule_type,
            "description": description,
            "last_triggered": last_triggered or time.time(),
            "status": self.ACTIVE,
            "created_at": time.time(),
            "trigger_count": 0,
            "expired_at": None,  # 过期时间
        }
    
    def trigger_rule(self, rule_id: str):
        """触发规则.
        
        Args:
            rule_id: 规则ID
        """
        if rule_id not in self._rules:
            return
        
        rule = self._rules[rule_id]
        rule["last_triggered"] = time.time()
        rule["trigger_count"] += 1
        self._trigger_counts[rule_id] += 1
        
        # 恢复过期规则
        if rule["status"] == self.EXPIRED:
            rule["status"] = self.ACTIVE
            rule["expired_at"] = None
    
    def audit(self) -> list[dict]:
        """执行审计.
        
        Returns:
            list: 审计结果列表
        """
        results = []
        now = time.time()
        
        for rule_id, rule in self._rules.items():
            days_since = (now - rule["last_triggered"]) / 86400
            
            # 安全规则不检查(除非配置为可过期)
            if rule["type"] == "security" and not self._security_expires:
                continue
            
            # 惰性检测
            if (days_since > self._inert_days and 
                rule["status"] == self.ACTIVE):
                rule["status"] = self.INERT
                results.append({
                    "rule": rule_id,
                    "type": rule["type"],
                    "status": self.INERT,
                    "days_since_trigger": round(days_since, 1),
                    "trigger_count": rule["trigger_count"],
                    "action": "marked_inert",
                    "description": rule.get("description", ""),
                })
            
            # 过期检测
            elif days_since > self._expiry_days and rule["status"] != self.ARCHIVED:
                if rule["status"] != self.EXPIRED:
                    rule["status"] = self.EXPIRED
                    rule["expired_at"] = now
                    results.append({
                        "rule": rule_id,
                        "type": rule["type"],
                        "status": self.EXPIRED,
                        "days_since_trigger": round(days_since, 1),
                        "trigger_count": rule["trigger_count"],
                        "action": "expired",
                        "description": rule.get("description", ""),
                    })
                
                # 归档检测
                if rule.get("expired_at") and (now - rule["expired_at"]) > self._archive_days * 86400:
                    self._archive_rule(rule_id)
        
        self._audit_history.append({
            "ts": now,
            "results": len(results),
        })
        
        return results
    
    def _archive_rule(self, rule_id: str):
        """归档规则.
        
        Args:
            rule_id: 规则ID
        """
        rule = self._rules.pop(rule_id, None)
        if rule:
            rule["archived_at"] = time.time()
            rule["status"] = self.ARCHIVED
            self._archive.append(rule)
    
    def reinstate(self, rule_id: str) -> bool:
        """恢复规则.
        
        Args:
            rule_id: 规则ID
        
        Returns:
            bool: 是否成功
        """
        # 先查归档
        for i, archived in enumerate(self._archive):
            if archived.get("rule_id") == rule_id or list(archived.keys())[0] == rule_id:
                rule = self._archive.pop(i)
                rule["status"] = self.ACTIVE
                rule["last_triggered"] = time.time()
                self._rules[rule_id] = rule
                return True
        
        # 查活跃规则
        if rule_id in self._rules:
            self._rules[rule_id]["status"] = self.ACTIVE
            self._rules[rule_id]["last_triggered"] = time.time()
            return True
        
        return False
    
    def get_rules_by_status(self, status: str) -> list[dict]:
        """按状态获取规则.
        
        Args:
            status: 状态
        
        Returns:
            list: 匹配的规则列表
        """
        return [
            {"rule_id": rid, **r}
            for rid, r in self._rules.items()
            if r["status"] == status
        ]
    
    def cleanup_archive(self, max_age_days: int = 30) -> int:
        """清理过期归档.
        
        Args:
            max_age_days: 最大保留天数
        
        Returns:
            int: 清理数量
        """
        cutoff = time.time() - max_age_days * 86400
        original = len(self._archive)
        self._archive = [a for a in self._archive if a.get("archived_at", 0) > cutoff]
        return original - len(self._archive)
    
    def get_stats(self) -> dict:
        """获取统计."""
        status_counts = defaultdict(int)
        for rule in self._rules.values():
            status_counts[rule["status"]] += 1
        
        type_counts = defaultdict(int)
        for rule in self._rules.values():
            type_counts[rule["type"]] += 1
        
        return {
            "total_rules": len(self._rules),
            "status_counts": dict(status_counts),
            "type_counts": dict(type_counts),
            "archived": len(self._archive),
            "audits_performed": len(self._audit_history),
            "total_triggers": sum(self._trigger_counts.values()),
        }
