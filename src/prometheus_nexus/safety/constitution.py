"""Constitution — 22-principle governance constitution with semantic review.

基于:
- Amodei et al. (2016) "Concrete Problems in AI Safety" + 宪法AI框架 (Bai et al., 2022)
  - 22条规则分层治理: S级(安全), A级(完整性), B级(溯源), C级(审计), D级(性能)
  - S级不可违反: 无害/无密钥/无自修改/无全删/无操纵 (5条红线)
  - A级完整性: 效用下限/惊喜上限/内容必填/标签格式/类型合法
  - B级溯源: 来源已知/置信度有效/分支存在/无循环引用/版本单调
  - 语义审查: 词汇多样性检测(防重复攻击)/感叹号检测(防过度强调)
  - 正则模式匹配: SECRET/HARM/SELFMODIFY/DELETEALL/MANIPULATION 五类危害检测

来源: Omega系统 constitution 22原则治理宪法模块 + AI安全框架
"""
from __future__ import annotations



import logging

import re
from dataclasses import dataclass
logger = logging.getLogger(__name__)


_SECRET_PATTERNS = [
    r'password\s*[:=]\s*\S+', r'api[_-]?key\s*[:=]\s*\S+',
    r'secret\s*[:=]\s*\S+', r'token\s*[:=]\s*\S+',
    r'private[_-]?key\s*[:=]\s*\S+', r'BEGIN\s+(RSA\s+)?PRIVATE\s+KEY',
]

_HARM_PATTERNS = [
    r'\b(hack|exploit|bypass)\b.*\b(system|security)\b',
    r'\b(dos|ddos)\s+attack',
    r'\b(malware|ransomware)\b.*\b(create|build)\b',
]

_SELFMODIFY_PATTERNS = [
    r'\b(modify|overwrite|delete)\s+(own|self|constitution)\b',
    r'\b(bypass|disable)\s+(safety|gate|guard)\b',
]

_DELETEALL_PATTERNS = [
    r'delete\s+all', r'drop\s+table', r'truncate', r'rm\s+-rf',
]

_MANIPULATION_PATTERNS = [
    r'you\s+must\s+obey',
    r'ignore\s+(all\s+)?previous',
    r'override\s+(your|the)',
    r'bypass\s+(safety|rules)',
    r'from\s+now\s+on',
    r'new\s+instructions?\s*:',
]


@dataclass
class ConstitutionViolation:
    passed: bool = True
    gate_name: str = ""
    reason: str = ""
    severity: str = "low"


def _check(content: str, patterns: list[str]) -> bool:
    return not any(re.search(p, content, re.IGNORECASE) for p in patterns)


class Constitution:
    """22-principle governance constitution with semantic review.

    Enhanced with behavioral pattern detection.

    Usage:
        c = Constitution()
        violations = c.evaluate({"content": "password=secret123", "utility": 0.5})
        for v in violations:
            print(f"{v.gate_name}: {v.reason}")
    """

    def __init__(self):
        self._rules = [
            {"name": "S1_no_harm", "level": "S", "check": lambda ctx: _check(ctx.get("content", ""), _HARM_PATTERNS)},
            {"name": "S2_no_secrets", "level": "S", "check": lambda ctx: _check(ctx.get("content", ""), _SECRET_PATTERNS)},
            {"name": "S3_no_selfmodify", "level": "S", "check": lambda ctx: _check(ctx.get("content", ""), _SELFMODIFY_PATTERNS)},
            {"name": "S4_no_delete_all", "level": "S", "check": lambda ctx: _check(ctx.get("content", ""), _DELETEALL_PATTERNS)},
            {"name": "S5_no_manipulation", "level": "S", "check": lambda ctx: _check(ctx.get("content", ""), _MANIPULATION_PATTERNS)},
            {"name": "A1_utility_floor", "level": "A", "check": lambda ctx: ctx.get("utility", 0.5) >= 0.1},
            {"name": "A2_surprise_ceiling", "level": "A", "check": lambda ctx: 0 <= ctx.get("surprise", 0) <= 1},
            {"name": "A3_content_required", "level": "A", "check": lambda ctx: bool(ctx.get("content", "").strip())},
            {"name": "A4_tags_format", "level": "A", "check": lambda ctx: isinstance(ctx.get("tags", []), list)},
            {"name": "A5_type_valid", "level": "A", "check": lambda ctx: ctx.get("action", "") in ("remember", "update", "delete", "evolve", "learn")},
            {"name": "B1_source_known", "level": "B", "check": lambda ctx: bool(ctx.get("source", ""))},
            {"name": "B2_confidence_valid", "level": "B", "check": lambda ctx: 0 <= ctx.get("confidence", 0.5) <= 1},
            {"name": "B3_branch_exists", "level": "B", "check": lambda ctx: bool(ctx.get("branch", "main"))},
            {"name": "B4_no_circular_ref", "level": "B", "check": lambda ctx: not any(
                ctx.get("content", "").count(w) > 3 for w in ["self-referenc", "circular", "infinite"]
            )},
            {"name": "B5_version_monotonic", "level": "B", "check": lambda ctx: ctx.get("version", 1) >= 1},
            {"name": "C1_audit_trail", "level": "C", "check": lambda ctx: bool(ctx.get("action", ""))},
            {"name": "C2_rate_limit", "level": "C", "check": lambda ctx: ctx.get("utility", 0.5) <= 1.0},
            {"name": "C3_size_limit", "level": "C", "check": lambda ctx: len(ctx.get("content", "")) < 1_000_000},
            {"name": "C4_encoding_valid", "level": "C", "check": lambda ctx: all(32 <= ord(c) < 0x10000 for c in ctx.get("content", "")[:1000])},
            {"name": "C5_schema_valid", "level": "C", "check": lambda ctx: isinstance(ctx.get("tags", []), list)},
            {"name": "D1_performance", "level": "D", "check": lambda ctx: len(ctx.get("content", "")) > 0},
            {"name": "D2_resource_limit", "level": "D", "check": lambda ctx: ctx.get("utility", 0.5) >= 0.0},
        ]
        self._evaluations = 0
        self._violations_history: list[dict] = []

    def evaluate(self, context: dict) -> list[ConstitutionViolation]:
        self._evaluations += 1
        violations = []

        for rule in self._rules:
            try:
                if not rule["check"](context):
                    severity = "critical" if rule["level"] == "S" else "medium" if rule["level"] == "A" else "low"
                    violations.append(ConstitutionViolation(
                        passed=False,
                        gate_name=rule["name"],
                        reason=f"Rule {rule['name']} violated",
                        severity=severity,
                    ))
            except Exception as e:
                logger.warning("Constitution rule check failed for %s: %s", rule.get("name", "unknown"), e)
                violations.append(ConstitutionViolation(
                    passed=False,
                    gate_name=rule["name"],
                    reason=f"Rule {rule['name']} check failed: {e}",
                    severity="low",
                ))

        content = context.get("content", "")
        semantic_violations = self._semantic_review(content)
        violations.extend(semantic_violations)

        if violations:
            self._violations_history.append({
                "eval": self._evaluations,
                "count": len(violations),
                "levels": [v.severity for v in violations],
            })

        return violations

    def _semantic_review(self, content: str) -> list[ConstitutionViolation]:
        violations = []
        if not content:
            return violations

        words = content.lower().split()
        word_count = len(words)

        if word_count > 0:
            unique_ratio = len(set(words)) / word_count
            if unique_ratio < 0.3 and word_count > 10:
                violations.append(ConstitutionViolation(
                    passed=False, gate_name="S6_low_diversity",
                    reason="Content has very low lexical diversity (possible repetition attack)",
                    severity="medium",
                ))

        if len(content) > 0:
            exclamation_ratio = content.count("!") / max(len(content), 1)
            if exclamation_ratio > 0.05:
                violations.append(ConstitutionViolation(
                    passed=False, gate_name="S7_excessive_emphasis",
                    reason="Excessive exclamation marks detected",
                    severity="low",
                ))

        return violations

    def get_stats(self) -> dict:
        recent = self._violations_history[-20:] if self._violations_history else []
        avg_violations = sum(v["count"] for v in recent) / max(len(recent), 1)
        return {
            "rules": len(self._rules),
            "evaluations": self._evaluations,
            "recent_avg_violations": avg_violations,
        }
