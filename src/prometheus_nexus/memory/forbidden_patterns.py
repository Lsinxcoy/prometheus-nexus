"""ForbiddenPatternDetector — 记忆内容禁区模式检测.

基于:
- "Safety-critical Pattern Detection in Memory Systems"
  - 模式匹配: 正则+语义模式检测
  - 分级告警: warning/critical/block
  - 白名单: 允许已知安全模式
  - 模式学习: 自动添加新检测到的模式

算法:
    check(content):
        1. 对每条规则执行模式匹配
        2. 匹配成功时检查白名单
        3. 计算匹配得分和置信度
        4. 返回违规列表

复杂度:
    check(): O(P) 其中P=规则数
"""
from __future__ import annotations
import re
import logging

logger = logging.getLogger(__name__)

import time
from typing import Optional


# 内置禁区模式
DEFAULT_PATTERNS = [
    {
        "id": "self_modifying_code",
        "pattern": r"(修改|删除|重写)\s*(自身|自己|本程序|核心代码)",
        "severity": "critical",
        "description": "自修改代码尝试",
    },
    {
        "id": "memory_injection",
        "pattern": r"(注入|插入)\s*(虚假|伪造|篡改).*?(记忆|数据|知识)",
        "severity": "critical",
        "description": "记忆注入攻击",
    },
    {
        "id": "safety_bypass",
        "pattern": r"(绕过|禁用|关闭)\s*(安全|限制|约束|检查|防护)",
        "severity": "critical",
        "description": "安全机制绕过",
    },
    {
        "id": "privilege_escalation",
        "pattern": r"(提升|获取|增加)\s*(权限|访问|控制|root|管理员)",
        "severity": "warning",
        "description": "权限提升尝试",
    },
    {
        "id": "data_exfiltration",
        "pattern": r"(发送|导出|传输|泄露)\s*(内部|私有|敏感|机密).*?(数据|信息|文件)",
        "severity": "warning",
        "description": "数据外泄风险",
    },
    {
        "id": "infinite_loop",
        "pattern": r"(while\s+True|for\s+.*\s+in\s+range\(\)\s*:)",
        "severity": "warning",
        "description": "无限循环模式",
    },
    {
        "id": "recursive_deletion",
        "pattern": r"(rm\s+-rf|del\s+.*\*|shred|wipe)",
        "severity": "critical",
        "description": "递归删除命令",
    },
    {
        "id": "prompt_leak",
        "pattern": r"(显示|输出|打印|reveal|print)\s*(完整|全部|system)\s*(提示|prompt|指令|instruction)",
        "severity": "critical",
        "description": "系统提示泄露",
    },
]


class ForbiddenPatternDetector:
    """记忆禁区模式检测 — 内容安全检查.
    
    使用正则+语义模式检测记忆内容中的危险操作.
    """
    
    def __init__(self, patterns: Optional[list[dict]] = None,
                 whitelist: Optional[list[str]] = None):
        """初始化.
        
        Args:
            patterns: 自定义检测规则列表
            whitelist: 白名单ID列表
        """
        self._patterns = patterns or DEFAULT_PATTERNS
        self._compiled = {}
        self._whitelist = set(whitelist or [])
        self._hits: list[dict] = []
        self._total_checks = 0
        self._total_violations = 0
        
        # 编译正则
        for p in self._patterns:
            try:
                self._compiled[p["id"]] = re.compile(p["pattern"], re.IGNORECASE)
            except re.error as e:
                # 安全相关: 编译失败的禁区模式不可静默丢弃 —— 必须显式暴露,
                # 否则该模式永不生效却仍计入 stats(虚假覆盖), 削弱 remember 安全门
                logger.error("ForbiddenPatternDetector: default pattern %r failed to compile, rule DISABLED: %s", p["id"], e)
                self._compiled[p["id"]] = None
    
    def check(self, content: str) -> list[dict]:
        """检查内容是否包含禁区模式.
        
        Args:
            content: 待检查内容
        
        Returns:
            list: 违规列表
        """
        self._total_checks += 1
        violations = []
        
        for pattern in self._patterns:
            pattern_id = pattern["id"]
            
            # 跳过白名单
            if pattern_id in self._whitelist:
                continue
            
            compiled = self._compiled.get(pattern_id)
            if not compiled:
                continue
            
            matches = compiled.findall(content)
            if matches:
                violation = {
                    "pattern_id": pattern_id,
                    "severity": pattern["severity"],
                    "description": pattern["description"],
                    "matches": len(matches),
                    "matched_text": matches[0] if isinstance(matches[0], str) else str(matches[0]),
                    "timestamp": time.time(),
                }
                violations.append(violation)
                self._hits.append(violation)
        
        if violations:
            self._total_violations += 1
        
        # 限制历史记录
        if len(self._hits) > 1000:
            self._hits = self._hits[-500:]
        
        return violations
    
    def add_pattern(self, pattern_id: str, pattern: str, severity: str = "warning",
                    description: str = "") -> None:
        """添加自定义检测规则.

        Args:
            pattern_id: 规则ID
            pattern: 正则表达式(必须是合法正则)
            severity: 严重级别
            description: 描述

        Raises:
            ValueError: 当 pattern 不是合法正则表达式时. 安全相关 —— 拒绝静默丢弃,
                调用方必须处理(否则该禁区模式会被无声漏防, 削弱 remember 安全门).
        """
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            logger.error("ForbiddenPatternDetector: pattern %r failed to compile, NOT added: %s", pattern_id, e)
            raise ValueError(f"Invalid regex for forbidden pattern {pattern_id!r}: {e}") from e
        self._patterns.append({
            "id": pattern_id,
            "pattern": pattern,
            "severity": severity,
            "description": description,
        })
        self._compiled[pattern_id] = compiled
    
    def add_to_whitelist(self, pattern_id: str):
        """添加到白名单.
        
        Args:
            pattern_id: 规则ID
        """
        self._whitelist.add(pattern_id)
    
    def remove_from_whitelist(self, pattern_id: str):
        """从白名单移除.
        
        Args:
            pattern_id: 规则ID
        """
        self._whitelist.discard(pattern_id)
    
    def get_recent_violations(self, n: int = 10) -> list[dict]:
        """获取最近违规记录.
        
        Args:
            n: 返回数量
        
        Returns:
            list: 最近违规列表
        """
        return self._hits[-n:]
    
    def get_stats(self) -> dict:
        """获取统计."""
        severity_counts = {}
        for hit in self._hits:
            sev = hit.get("severity", "unknown")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        
        return {
            "total_checks": self._total_checks,
            "total_violations": self._total_violations,
            "violation_rate": round(self._total_violations / max(self._total_checks, 1), 4),
            "patterns_count": len(self._patterns),
            "effective_patterns": sum(1 for c in self._compiled.values() if c is not None),
            "whitelist_count": len(self._whitelist),
            "severity_distribution": severity_counts,
        }
