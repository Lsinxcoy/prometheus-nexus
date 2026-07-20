"""RiskClassifiedApproval — 风险分级审批系统

借鉴OpenOPC的Risk-Classified Approval机制：
- 根据操作风险等级自动选择审批流程
- 低风险：自动批准
- 中风险：单人审批
- 高风险：多人审批/委员会审批
- 支持审批链和委托
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from collections import defaultdict

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """风险等级"""
    LOW = "low"        # 自动批准
    MEDIUM = "medium"  # 单人审批
    HIGH = "high"      # 双人审批
    CRITICAL = "critical"  # 委员会审批


@dataclass
class ApprovalRequest:
    """审批请求"""
    request_id: str
    operation: str
    risk_level: RiskLevel
    context: dict[str, Any] = field(default_factory=dict)
    requested_by: str = ""
    created_at: float = 0.0
    approved_by: list[str] = field(default_factory=list)
    status: str = "pending"  # pending/approved/rejected/expired
    reason: str = ""


@dataclass
class ApprovalPolicy:
    """审批策略配置"""
    # 风险阈值
    low_risk_threshold: float = 0.3
    medium_risk_threshold: float = 0.6
    high_risk_threshold: float = 0.8

    # 审批要求
    require_single_approval: bool = True
    require_double_approval: bool = True
    require_committee: bool = True

    # 时间限制
    approval_timeout_seconds: float = 300.0  # 5分钟

    # 委托规则
    allow_delegation: bool = True
    delegation_max_depth: int = 3


class RiskClassifiedApproval:
    """风险分级审批系统

    根据操作风险等级自动选择审批流程，支持多级审批和委托。
    """

    def __init__(self, policy: ApprovalPolicy | None = None):
        self._policy = policy or ApprovalPolicy()
        self._requests: dict[str, ApprovalRequest] = {}
        self._approvers: dict[str, list[str]] = defaultdict(list)  # approver -> requests
        self._stats = {
            "total_requests": 0,
            "auto_approved": 0,
            "single_approved": 0,
            "double_approved": 0,
            "committee_approved": 0,
            "rejected": 0,
            "expired": 0,
        }

    def create_request(
        self,
        request_id: str,
        operation: str,
        risk_score: float,
        context: dict[str, Any] | None = None,
        requested_by: str = "",
    ) -> ApprovalRequest:
        """创建审批请求

        Args:
            request_id: 请求ID
            operation: 操作名称
            risk_score: 风险分数 [0, 1]
            context: 上下文信息
            requested_by: 请求发起者

        Returns:
            ApprovalRequest对象
        """
        risk_level = self._classify_risk(risk_score)

        request = ApprovalRequest(
            request_id=request_id,
            operation=operation,
            risk_level=risk_level,
            context=context or {},
            requested_by=requested_by,
            created_at=time.time(),
        )

        self._requests[request_id] = request
        self._stats["total_requests"] += 1

        # 低风险自动批准
        if risk_level == RiskLevel.LOW:
            request.status = "approved"
            request.reason = "Auto-approved (low risk)"
            self._stats["auto_approved"] += 1
            logger.info("Auto-approved request %s (risk=%.2f)", request_id, risk_score)

        return request

    def approve(self, request_id: str, approver: str) -> bool:
        """审批请求

        Args:
            request_id: 请求ID
            approver: 审批人

        Returns:
            是否成功
        """
        if request_id not in self._requests:
            return False

        request = self._requests[request_id]

        # 检查是否已过期
        if self._is_expired(request):
            request.status = "expired"
            self._stats["expired"] += 1
            return False

        # 添加审批人
        request.approved_by.append(approver)
        self._approvers[approver].append(request_id)

        # 检查是否满足审批要求
        required = self._get_required_approvals(request.risk_level)
        if len(request.approved_by) >= required:
            request.status = "approved"
            self._update_stats(request.risk_level)
            logger.info("Approved request %s by %s (risk=%s)", request_id, approver, request.risk_level.value)
            return True

        logger.debug("Request %s awaiting more approvals (got %d/%d)",
                     request_id, len(request.approved_by), required)
        return False

    def reject(self, request_id: str, approver: str, reason: str = "") -> bool:
        """拒绝请求

        Args:
            request_id: 请求ID
            approver: 审批人
            reason: 拒绝原因

        Returns:
            是否成功
        """
        if request_id not in self._requests:
            return False

        request = self._requests[request_id]
        request.status = "rejected"
        request.reason = reason
        self._stats["rejected"] += 1

        logger.warning("Rejected request %s by %s: %s", request_id, approver, reason)
        return True

    def get_pending_requests(self, approver: str | None = None) -> list[ApprovalRequest]:
        """获取待处理请求

        Args:
            approver: 可选，指定审批人的请求

        Returns:
            待处理请求列表
        """
        pending = []
        for req in self._requests.values():
            if req.status != "pending":
                continue
            if approver and req.request_id not in self._approvers.get(approver, []):
                continue
            pending.append(req)
        return pending

    def check_expirations(self) -> int:
        """检查并标记过期请求

        Returns:
            过期请求数量
        """
        expired_count = 0
        for req in self._requests.values():
            if req.status == "pending" and self._is_expired(req):
                req.status = "expired"
                self._stats["expired"] += 1
                expired_count += 1
        return expired_count

    def _classify_risk(self, score: float) -> RiskLevel:
        """分类风险等级"""
        if score < self._policy.low_risk_threshold:
            return RiskLevel.LOW
        elif score < self._policy.medium_risk_threshold:
            return RiskLevel.MEDIUM
        elif score < self._policy.high_risk_threshold:
            return RiskLevel.HIGH
        else:
            return RiskLevel.CRITICAL

    def _get_required_approvals(self, risk_level: RiskLevel) -> int:
        """获取所需审批人数"""
        if risk_level == RiskLevel.LOW:
            return 0  # 自动批准
        elif risk_level == RiskLevel.MEDIUM:
            return 1
        elif risk_level == RiskLevel.HIGH:
            return 2
        else:
            return 3  # 委员会

    def _is_expired(self, request: ApprovalRequest) -> bool:
        """检查是否过期"""
        elapsed = time.time() - request.created_at
        return elapsed > self._policy.approval_timeout_seconds

    def _update_stats(self, risk_level: RiskLevel) -> None:
        """更新统计"""
        if risk_level == RiskLevel.MEDIUM:
            self._stats["single_approved"] += 1
        elif risk_level == RiskLevel.HIGH:
            self._stats["double_approved"] += 1
        elif risk_level == RiskLevel.CRITICAL:
            self._stats["committee_approved"] += 1

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "pending_requests": sum(1 for r in self._requests.values() if r.status == "pending"),
            "active_approvers": len(self._approvers),
        }
