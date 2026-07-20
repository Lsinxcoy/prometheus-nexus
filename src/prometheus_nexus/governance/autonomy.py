"""AutonomyLevel — 自治决策与权限门控.

基于:
- "Confidence-Based Autonomy for AI Systems"
  - 自治级别: manual/assisted/semi/full
  - 信心门控: 信心不足时请求人工确认
  - 进化审查: 高风险变更需额外验证
  - 信任累积: 成功决策提升自治级别

算法:
    can_act(action, confidence):
        1. 评估动作风险
        2. 检查信心阈值
        3. 返回是否可以执行
    
    escalate(action, evidence):
        1. 提交人工审查
        2. 记录审查结果
        3. 更新信任级别

复杂度:
    can_act(): O(1)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
from enum import Enum


class AutonomyLevel(Enum):
    """自治级别."""
    MANUAL = "manual"           # 完全人工控制
    ASSISTED = "assisted"       # 建议+人工确认
    SEMI_AUTONOMOUS = "semi"    # 低风险自动,高风险确认
    FULL_AUTONOMOUS = "full"    # 完全自主
    # 兼容别名 (life.py 使用)
    L0_MANUAL = "manual"
    L1_ASSISTED = "assisted"
    L2_SUPERVISED = "semi"
    L3_AUTONOMOUS = "full"


class ConfidenceGate:
    """信心门控 — 基于置信度决定自治级别.
    
    低风险动作可自动执行,高风险需要人工审查.
    """
    
    # 动作风险分类
    LOW_RISK = {"read", "query", "search", "get_stats", "list", "get"}
    MEDIUM_RISK = {"update", "modify", "add", "create", "write"}
    HIGH_RISK = {"delete", "remove", "drop", "reset", "revoke", "destroy"}
    
    def __init__(self, current_level: str = "assisted",
                 low_threshold: float = 0.3,
                 medium_threshold: float = 0.6,
                 high_threshold: float = 0.85):
        """初始化.
        
        Args:
            current_level: 当前自治级别
            low_threshold: 低风险信心阈值
            medium_threshold: 中风险信心阈值
            high_threshold: 高风险信心阈值
        """
        self._level = current_level
        self._low_threshold = low_threshold
        self._medium_threshold = medium_threshold
        self._high_threshold = high_threshold
        self._trust_score = 0.5
        self._decision_log: list[dict] = []
    
    def can_act(self, action: str, confidence: float = 0.5) -> dict:
        """检查是否可以执行动作.
        
        Args:
            action: 动作名称
            confidence: 置信度 [0, 1]
        
        Returns:
            dict: 检查结果
        """
        # 评估风险级别
        risk = self._classify_risk(action)
        
        # 根据自治级别和风险判断
        if self._level == "manual":
            approved = False
            reason = "manual mode requires human approval"
        elif self._level == "full":
            approved = confidence >= 0.2
            reason = "full autonomy" if approved else "confidence too low"
        elif self._level == "semi":
            if risk == "low":
                approved = confidence >= self._low_threshold
                reason = f"low risk, confidence {confidence:.2f}"
            elif risk == "medium":
                approved = confidence >= self._medium_threshold
                reason = f"medium risk, confidence {confidence:.2f}"
            else:
                approved = False
                reason = "high risk requires human approval in semi mode"
        else:  # assisted
            if risk == "low" and confidence >= self._low_threshold:
                approved = True
                reason = "assisted: low risk approved"
            else:
                approved = False
                reason = "assisted: needs confirmation"
        
        result = {
            "approved": approved,
            "action": action,
            "risk": risk,
            "confidence": confidence,
            "autonomy_level": self._level,
            "reason": reason,
        }
        
        self._decision_log.append(result)
        if len(self._decision_log) > 500:
            self._decision_log = self._decision_log[-250:]
        
        return result
    
    def record_outcome(self, action: str, success: bool) -> None:
        """记录决策结果,更新信任分.
        
        Args:
            action: 动作名称
            success: 是否成功
        """
        if success:
            self._trust_score = min(1.0, self._trust_score + 0.02)
        else:
            self._trust_score = max(0.0, self._trust_score - 0.05)
        
        # 自动升级检查
        if self._trust_score > 0.9 and self._level == "assisted":
            self._level = "semi"
        elif self._trust_score > 0.95 and self._level == "semi":
            self._level = "full"
        elif self._trust_score < 0.3 and self._level != "manual":
            self._level = "assisted"
    
    def _classify_risk(self, action: str) -> str:
        """分类动作风险.
        
        Args:
            action: 动作名称
        
        Returns:
            str: 风险级别
        """
        action_lower = action.lower()
        if any(kw in action_lower for kw in self.HIGH_RISK):
            return "high"
        if any(kw in action_lower for kw in self.MEDIUM_RISK):
            return "medium"
        return "low"
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "autonomy_level": self._level,
            "trust_score": round(self._trust_score, 4),
            "total_decisions": len(self._decision_log),
        }
    
    # 兼容别名: life.py 调用 check(context_dict)
    def check(self, context: dict) -> dict:
        """兼容性检查 (接受上下文字典)."""
        action = context.get("action", context.get("context", "unknown"))
        confidence = context.get("fitness", context.get("confidence", 0.5))
        if isinstance(action, str):
            pass
        else:
            action = str(action)
        return self.can_act(action, float(confidence))


class EvolutionGrill:
    """进化审查 — 高风险变更多级验证.
    
    进化操作需通过多重安全检查.
    """
    
    def __init__(self, min_checks: int = 3):
        """初始化.
        
        Args:
            min_checks: 最小检查数
        """
        self._min_checks = min_checks
        self._audit_log: list[dict] = []
    
    def review(self, change: dict, checks: list[dict] | None = None) -> dict:
        """审查变更.
        
        Args:
            change: 变更描述
            checks: 检查结果列表 (可选, 默认为空列表)
        
        Returns:
            dict: 审查报告
        """
        if checks is None:
            checks = []
        passed = sum(1 for c in checks if c.get("passed", False))
        failed = len(checks) - passed
        
        sufficient = len(checks) >= self._min_checks and passed >= self._min_checks
        # Fail-CLOSED: a high-risk-change gate may only approve when enough
        # checks ran AND every one passed. An empty/missing checks list (or any
        # failed check) must NOT auto-approve -- that is a fail-open that hides
        # unreviewed changes behind an `approved=True` signal.
        approved = sufficient and failed == 0
        if not approved:
            logger.warning(
                "EvolutionGrill: change NOT approved (fail-closed) "
                "checks=%d passed=%d failed=%d min=%d",
                len(checks), passed, failed, self._min_checks,
            )
        
        report = {
            "approved": approved,
            "change": change.get("description", "")[:100],
            "checks_total": len(checks),
            "checks_passed": passed,
            "checks_failed": failed,
            "sufficient_checks": sufficient,
            "ts": time.time(),
        }
        
        self._audit_log.append(report)
        if len(self._audit_log) > 200:
            self._audit_log = self._audit_log[-100:]
        
        return report
    
    def get_stats(self) -> dict:
        """获取统计."""
        if not self._audit_log:
            return {"reviews": 0}
        
        approved = sum(1 for r in self._audit_log if r["approved"])
        return {
            "reviews": len(self._audit_log),
            "approval_rate": round(approved / len(self._audit_log), 4),
        }

# 兼容别名 - TrustLevel 映射到 AutonomyLevel
from enum import Enum as _Enum

class TrustLevel(Enum):
    """信任等级 - 映射到 AutonomyLevel"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
