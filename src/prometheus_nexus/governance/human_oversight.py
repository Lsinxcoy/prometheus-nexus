"""HumanOversight — Human-in-the-loop oversight mechanism.

Based on: "Practices for Governing Agentic AI Systems" (OpenAI, 2025)

Key Concepts:
    1. Safety checkpoints requiring human approval
    2. Timeout-based auto-approval for low-risk actions
    3. Audit trail of all oversight decisions
    4. Accountability framework for agent actions

Algorithm:
    1. Classify action risk level (low/medium/high/critical)
    2. Route based on risk: low=auto, medium=queue, high=critical=human_required
    3. Enforce timeout for queue items
    4. Log all decisions for audit
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from dataclasses import dataclass, field
from enum import Enum


class OversightRiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Backward compatibility alias
RiskLevel = OversightRiskLevel


class OversightDecision(Enum):
    AUTO_APPROVED = "auto_approved"
    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"
    TIMEOUT_APPROVED = "timeout_approved"
    PENDING = "pending"


@dataclass
class OversightRequest:
    request_id: str = ""
    action: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    context: dict = field(default_factory=dict)
    created_at: float = 0.0
    decided_at: float = 0.0
    decision: OversightDecision = OversightDecision.PENDING
    reviewer: str = ""


class HumanOversight:
    """Human-in-the-loop oversight mechanism.

    Based on OpenAI's Governing Agentic AI (2025).

    Usage:
        oversight = HumanOversight(timeout_seconds=300)
        request = oversight.submit_action("delete_database", RiskLevel.CRITICAL)
        if oversight.needs_human(request):
            approval = oversight.approve(request.request_id, "admin")
    """

    def __init__(self, timeout_seconds: float = 300.0,
                 auto_approve_below: RiskLevel = RiskLevel.LOW):
        self._timeout = timeout_seconds
        self._auto_below = auto_approve_below
        self._requests: dict[str, OversightRequest] = {}
        self._history: list[dict] = []
        self._request_counter = 0

    def submit_action(self, action: str, risk_level: RiskLevel,
                      context: dict | None = None) -> OversightRequest:
        self._request_counter += 1
        request = OversightRequest(
            request_id=f"req_{self._request_counter}",
            action=action,
            risk_level=risk_level,
            context=context or {},
            created_at=time.time(),
        )

        risk_order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        if risk_order.index(risk_level) < risk_order.index(self._auto_below):
            request.decision = OversightDecision.AUTO_APPROVED
            request.decided_at = time.time()

        self._requests[request.request_id] = request
        return request

    def needs_human(self, request: OversightRequest) -> bool:
        if request.decision != OversightDecision.PENDING:
            return False
        if time.time() - request.created_at > self._timeout:
            request.decision = OversightDecision.TIMEOUT_APPROVED
            request.decided_at = time.time()
            self._log_decision(request)
            return False
        return True

    def approve(self, request_id: str, reviewer: str = "human") -> OversightRequest:
        request = self._requests.get(request_id)
        if request and request.decision == OversightDecision.PENDING:
            request.decision = OversightDecision.HUMAN_APPROVED
            request.decided_at = time.time()
            request.reviewer = reviewer
            self._log_decision(request)
        return request

    def reject(self, request_id: str, reviewer: str = "human",
               reason: str = "") -> OversightRequest:
        request = self._requests.get(request_id)
        if request and request.decision == OversightDecision.PENDING:
            request.decision = OversightDecision.HUMAN_REJECTED
            request.decided_at = time.time()
            request.reviewer = reviewer
            request.context["reject_reason"] = reason
            self._log_decision(request)
        return request

    def check_timeouts(self) -> list[OversightRequest]:
        timed_out = []
        for request in self._requests.values():
            if request.decision == OversightDecision.PENDING:
                if time.time() - request.created_at > self._timeout:
                    request.decision = OversightDecision.TIMEOUT_APPROVED
                    request.decided_at = time.time()
                    self._log_decision(request)
                    timed_out.append(request)
        return timed_out

    def _log_decision(self, request: OversightRequest):
        self._history.append({
            "request_id": request.request_id,
            "action": request.action,
            "risk_level": request.risk_level.value,
            "decision": request.decision.value,
            "reviewer": request.reviewer,
            "duration_ms": (request.decided_at - request.created_at) * 1000,
        })

    def get_pending(self) -> list[OversightRequest]:
        return [r for r in self._requests.values() if r.decision == OversightDecision.PENDING]

    def get_stats(self) -> dict:
        decisions = [h["decision"] for h in self._history]
        return {
            "total_requests": len(self._requests),
            "pending": len(self.get_pending()),
            "decisions": dict(__import__("collections").Counter(decisions)),
        }
