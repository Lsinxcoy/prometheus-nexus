"""TwoLevelBlockerEscalation — 两级Blocker升级引擎

借鉴OpenOPC的Two-Level Blocker Escalation和Risk-Classified Approval机制：
- Level 1: 本地快速检查（低延迟，高吞吐）
- Level 2: 全局深度检查（高延迟，高精度）
- 根据风险等级自动选择检查级别
- 支持升级：L1失败后自动升级到L2
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class BlockerCheck:
    """Blocker检查结果"""
    passed: bool
    risk_level: RiskLevel
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    check_level: int = 1  # 1 or 2
    duration_ms: float = 0.0


@dataclass
class BlockerPolicy:
    """Blocker策略配置"""
    # L1检查阈值
    l1_utility_threshold: float = 0.3
    l1_surprise_threshold: float = 0.8
    l1_content_min_length: int = 10

    # L2检查阈值（更严格）
    l2_utility_threshold: float = 0.5
    l2_surprise_threshold: float = 0.6
    l2_content_min_length: int = 50

    # 升级条件
    escalate_on_failure: bool = True  # L1失败时是否升级到L2
    escalate_on_high_risk: bool = True  # 高风险时直接使用L2


class TwoLevelBlockerEscalation:
    """两级Blocker升级引擎

    根据风险等级自动选择检查级别，支持升级机制。
    """

    def __init__(self, policy: BlockerPolicy | None = None):
        self._policy = policy or BlockerPolicy()
        self._stats = {
            "l1_checks": 0,
            "l2_checks": 0,
            "l1_passed": 0,
            "l1_failed_escalated": 0,
            "l2_passed": 0,
            "l2_failed": 0,
            "total_duration_ms": 0.0,
        }

    def evaluate(self, node: dict[str, Any], context: dict[str, Any] | None = None) -> BlockerCheck:
        """评估节点是否通过Blocker检查

        Args:
            node: 节点数据（包含utility, surprise, content等字段）
            context: 上下文信息

        Returns:
            BlockerCheck结果
        """
        context = context or {}
        start_time = time.time()

        # 确定初始风险等级
        risk_level = self._determine_risk_level(node, context)

        # 根据风险等级决定起始检查级别
        if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL) and self._policy.escalate_on_high_risk:
            # 高风险直接使用L2
            result = self._run_level2_check(node, context)
            result.check_level = 2
            self._update_stats(result, 2)
            return result

        # 从L1开始
        result = self._run_level1_check(node, context)
        result.check_level = 1
        self._update_stats(result, 1)

        if not result.passed and self._policy.escalate_on_failure:
            # L1失败，升级到L2
            result = self._run_level2_check(node, context)
            result.check_level = 2
            self._update_stats(result, 2)
            if not result.passed:
                self._stats["l1_failed_escalated"] += 1

        duration_ms = (time.time() - start_time) * 1000
        result.duration_ms = duration_ms
        self._stats["total_duration_ms"] += duration_ms

        return result

    def _determine_risk_level(self, node: dict[str, Any], context: dict[str, Any]) -> RiskLevel:
        """确定风险等级"""
        utility = node.get("utility", 0.5)
        surprise = node.get("surprise", 0.5)
        content_len = len(node.get("content", ""))

        # 低utility或高surprise表示高风险
        if utility < 0.2 or surprise > 0.9:
            return RiskLevel.CRITICAL
        elif utility < 0.4 or surprise > 0.7:
            return RiskLevel.HIGH
        elif utility < 0.6 or surprise > 0.5:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    def _run_level1_check(self, node: dict[str, Any], context: dict[str, Any]) -> BlockerCheck:
        """运行L1检查（快速、宽松）"""
        self._stats["l1_checks"] += 1

        utility = node.get("utility", 0.5)
        surprise = node.get("surprise", 0.5)
        content = node.get("content", "")

        checks = []

        # Utility检查
        if utility >= self._policy.l1_utility_threshold:
            checks.append(True)
        else:
            checks.append(False)

        # Surprise检查
        if surprise <= self._policy.l1_surprise_threshold:
            checks.append(True)
        else:
            checks.append(False)

        # Content长度检查
        if len(content) >= self._policy.l1_content_min_length:
            checks.append(True)
        else:
            checks.append(False)

        passed = all(checks)
        failed_reasons = []
        if not checks[0]:
            failed_reasons.append(f"utility too low ({utility:.2f})")
        if not checks[1]:
            failed_reasons.append(f"surprise too high ({surprise:.2f})")
        if not checks[2]:
            failed_reasons.append(f"content too short ({len(content)} chars)")

        return BlockerCheck(
            passed=passed,
            risk_level=self._determine_risk_level(node, context),
            reason="; ".join(failed_reasons) if failed_reasons else "All L1 checks passed",
            details={
                "utility": utility,
                "surprise": surprise,
                "content_length": len(content),
                "checks": checks,
            },
        )

    def _run_level2_check(self, node: dict[str, Any], context: dict[str, Any]) -> BlockerCheck:
        """运行L2检查（慢速、严格）"""
        self._stats["l2_checks"] += 1

        utility = node.get("utility", 0.5)
        surprise = node.get("surprise", 0.5)
        content = node.get("content", "")

        checks = []

        # 更严格的Utility检查
        if utility >= self._policy.l2_utility_threshold:
            checks.append(True)
        else:
            checks.append(False)

        # 更严格的Surprise检查
        if surprise <= self._policy.l2_surprise_threshold:
            checks.append(True)
        else:
            checks.append(False)

        # 更长的内容要求
        if len(content) >= self._policy.l2_content_min_length:
            checks.append(True)
        else:
            checks.append(False)

        # 额外检查：内容质量（简单启发式）
        quality_score = self._compute_content_quality(content)
        if quality_score >= 0.5:
            checks.append(True)
        else:
            checks.append(False)

        passed = all(checks)
        failed_reasons = []
        if not checks[0]:
            failed_reasons.append(f"utility too low for L2 ({utility:.2f})")
        if not checks[1]:
            failed_reasons.append(f"surprise too high for L2 ({surprise:.2f})")
        if not checks[2]:
            failed_reasons.append(f"content too short for L2 ({len(content)} chars)")
        if not checks[3]:
            failed_reasons.append(f"content quality too low ({quality_score:.2f})")

        return BlockerCheck(
            passed=passed,
            risk_level=self._determine_risk_level(node, context),
            reason="; ".join(failed_reasons) if failed_reasons else "All L2 checks passed",
            details={
                "utility": utility,
                "surprise": surprise,
                "content_length": len(content),
                "content_quality": quality_score,
                "checks": checks,
            },
        )

    def _compute_content_quality(self, content: str) -> float:
        """计算内容质量分数（简单启发式）"""
        if not content:
            return 0.0

        score = 0.0

        # 长度贡献
        length_contribution = min(len(content) / 100, 1.0)
        score += length_contribution * 0.3

        # 多样性贡献（不同字符数/总字符数）
        unique_chars = len(set(content))
        diversity = unique_chars / max(len(content), 1)
        score += diversity * 0.3

        # 结构贡献（有标点符号）
        punctuation_count = sum(1 for c in content if c in ".,!?;:")
        structure = min(punctuation_count / 5, 1.0)
        score += structure * 0.2

        # 词汇贡献（字母占比）
        letters = sum(1 for c in content if c.isalpha())
        wordiness = letters / max(len(content), 1)
        score += wordiness * 0.2

        return min(score, 1.0)

    def _update_stats(self, result: BlockerCheck, level: int) -> None:
        """更新统计"""
        if level == 1:
            if result.passed:
                self._stats["l1_passed"] += 1
        else:
            if result.passed:
                self._stats["l2_passed"] += 1
            else:
                self._stats["l2_failed"] += 1

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        avg_duration = 0.0
        total_checks = self._stats["l1_checks"] + self._stats["l2_checks"]
        if total_checks > 0:
            avg_duration = self._stats["total_duration_ms"] / total_checks

        return {
            **self._stats,
            "avg_duration_ms": avg_duration,
            "l1_pass_rate": self._stats["l1_passed"] / max(self._stats["l1_checks"], 1),
            "l2_pass_rate": self._stats["l2_passed"] / max(self._stats["l2_checks"], 1),
        }
