"""ToolTaxGate — 工具使用成本门控决策器，集成 G-STEP (arXiv 2605.00136) 语义噪声分析。

G-STEP 论文表明，在语义噪声条件下，工具使用的收益可能无法超过成本。
语义噪声包括：歧义性、信息不完整、矛盾信号等干扰因素。

核心发现：传统的 cost < gain 决策在无噪声环境下有效，但在语义噪声环境下，
噪声会同时降低估计增益的准确性和增加实际成本。G-STEP 提出了因子化干预框架
(Factorized Intervention Framework) 来处理这个问题。

当前实现了:
1. ToolTaxGate — 原有 3 组件成本结构 + 语义噪声调整
2. SemanticNoiseModeler — 估计当前上下文的语义噪声水平
3. GainEstimator — 动态增益估计，随语义噪声衰减
4. GSTEPGate — 完整的因子化干预决策

所有组件保持与原有接口兼容。
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

logger = logging.getLogger(__name__)

# 语义噪声维度
_NOISE_DIMENSIONS = {
    "ambiguity": {
        "keywords": ["maybe", "perhaps", "possibly", "might", "could", "unclear",
                     "uncertain", "ambiguous", "vague", "unclear", "roughly",
                     "approximately", "some", "a few", "several", "many"],
        "weight": 0.30,
    },
    "incomplete": {
        "keywords": ["missing", "incomplete", "need more", "not sure", "unknown",
                     "what about", "what if", "depends", "context needed",
                     "more information", "details missing", "incomplete info",
                     "TBD", "TODO", "placeholder", "to be determined"],
        "weight": 0.25,
    },
    "conflicting": {
        "keywords": ["but", "however", "although", "on the other hand",
                     "contradict", "conflict", "instead", "alternatively",
                     "versus", "vs", "rather than", "opposite", "disagree",
                     "inconsistent", "mismatch", "but also"],
        "weight": 0.25,
    },
    "noise": {
        "keywords": ["irrelevant", "unrelated", "off-topic", "random", "nonsense",
                     "garbage", "spam", "noise", "distraction", "extraneous",
                     "unnecessary detail", "tangent", "digression"],
        "weight": 0.20,
    },
}

# 原有常量（保持兼容）
_PROTOCOL_OVERHEAD = 0.15
_EXECUTION_GATE = 0.10

# 简单/中等/复杂任务关键词（保留）
_SIMPLE_COG_TASKS = {"calculate", "convert", "format", "today", "time", "weather", "math", "echo"}
_MODERATE_TASKS = {"search", "lookup", "translate", "summarize", "check", "find"}
_COMPLEX_TASKS = {"analyze", "compare", "optimize", "code", "compile", "debug", "deploy"}


# ======================================================================
# SemanticNoiseEstimator — 上下文级语义噪声快速估计 (arXiv 2605.00136)
# ======================================================================

class SemanticNoiseEstimator:
    """Quick semantic noise estimator for a given context string.

    Checks context for ambiguity indicators:
      - Question marks, uncertain phrasing
      - Multiple possible interpretations
      - Incomplete patterns (trailing ellipsis, dangling clauses)
      - Hedge words and vague quantifiers

    Produces a lightweight noise score (0.0–1.0) suitable for real-time
    tool-use gating decisions.

    Attributes:
        _estimates: history of past estimates for stats tracking.
    """

    # Weight per indicator category
    _WEIGHTS = {
        "question_ambiguity": 0.30,
        "hedge_vagueness": 0.30,
        "incomplete_pattern": 0.25,
        "multiple_interpretations": 0.15,
    }

    _HEDGE_WORDS = {
        "maybe", "perhaps", "possibly", "might", "could", "seems", "appears",
        "sort of", "kind of", "roughly", "approximately", "likely", "probably",
        "somewhat", "mostly", "generally", "tends to", "a bit",
    }

    _VAGUE_QUANTIFIERS = {
        "some", "several", "many", "a few", "a lot", "a bunch", "various",
        "numerous", "multiple", "countless", "quite a few",
    }

    def __init__(self) -> None:
        self._estimates: list[dict] = []

    def estimate(self, context: str) -> dict:
        """Estimate semantic noise in the provided *context* string.

        Args:
            context: The user query, task description, or conversational
                     context to analyse.

        Returns:
            A dict with keys:
                noise_score   : float  – estimated noise (0.0–1.0)
                factors       : dict   – per-factor scores
                signal_words  : list   – matched indicator keywords
                confidence    : float  – reliability of this estimate
                details       : str    – human-readable summary
        """
        low = context.lower()
        words = low.split()
        n = max(len(words), 1)

        signals: list[str] = []
        factor_scores: dict[str, float] = {}

        # 1. Question / ambiguity  — count '?' and interrogative starters
        q_count = context.count("?")
        interrogatives = sum(
            1 for w in words if w in {"what", "which", "how", "why", "when", "where", "who"}
        )
        question_factor = min(1.0, (q_count + interrogatives * 0.5) / 5.0)
        if question_factor > 0:
            factor_scores["question_ambiguity"] = round(question_factor, 3)
            if q_count:
                signals.append(f"{q_count} question(s)")

        # 2. Hedge / vagueness
        hedge_hits = [w for w in words if w in self._HEDGE_WORDS]
        vague_hits = [w for w in words if w in self._VAGUE_QUANTIFIERS]
        hedge_score = min(1.0, (len(hedge_hits) + len(vague_hits)) / (n * 0.05 + 1))
        if hedge_score > 0:
            factor_scores["hedge_vagueness"] = round(hedge_score, 3)
            if hedge_hits:
                signals.extend(hedge_hits[:3])

        # 3. Incomplete pattern — trailing "…", hanging "and" / "or", orphan clauses
        incomplete_score = 0.0
        for pat in (r"\.\.\.$", r"\.\.\.\s*$", r"\b(and|or|but|so)\s*$",
                    r"\b(if|when|while|because|although)\s*$",
                    r"\b(for example|such as|like|e\.g\.)\s*$",
                    r"\b(TBD|TODO|placeholder|to be determined)\s*"):
            if re.search(pat, low):
                incomplete_score = max(incomplete_score, 0.5)
                signals.append("incomplete pattern")
                break
        # Also penalise very short contexts (< 5 words) as inherently incomplete
        if n < 5:
            incomplete_score = max(incomplete_score, 0.3)
            signals.append("very short context")
        if incomplete_score > 0:
            factor_scores["incomplete_pattern"] = round(incomplete_score, 3)

        # 4. Multiple interpretations — "or", "either", "otherwise", "alternatively"
        or_count = low.count(" or ")
        multi_hits = sum(low.count(x) for x in ("either", "alternatively", "otherwise",
                                                 "on one hand", "on the other hand"))
        multi_score = min(1.0, (or_count * 0.25 + multi_hits * 0.3))
        if multi_score > 0:
            factor_scores["multiple_interpretations"] = round(multi_score, 3)
            if or_count >= 2:
                signals.append("multiple alternatives")

        # Weighted combination
        noise_score = 0.0
        for factor, weight in self._WEIGHTS.items():
            f_score = factor_scores.get(factor, 0.0)
            noise_score += f_score * weight
        noise_score = min(1.0, noise_score)

        # Confidence grows with context length
        confidence = min(1.0, n / 80.0)

        # Build detail string
        detail = f"noise={noise_score:.2f}"
        top = sorted(factor_scores.items(), key=lambda x: -x[1])[:2]
        if top:
            detail += f" ({', '.join(f'{k}={v:.2f}' for k, v in top)})"
        detail += f" | signals: {signals[:4]}" if signals else " | no strong signals"

        result = {
            "noise_score": round(noise_score, 3),
            "factors": factor_scores,
            "signal_words": signals[:6],
            "confidence": round(confidence, 3),
            "details": detail,
            "method": "SemanticNoiseEstimator",
        }
        self._estimates.append(result)
        return result

    def get_stats(self) -> dict:
        if not self._estimates:
            return {"total_estimates": 0}
        avg_noise = sum(e["noise_score"] for e in self._estimates) / len(self._estimates)
        return {
            "total_estimates": len(self._estimates),
            "avg_noise_score": round(avg_noise, 3),
        }


# ======================================================================
# Noise-adjusted gain helpers (arXiv 2605.00136 §3.2)
# ======================================================================

def noise_adjusted_gain(base_gain: float, noise_level: float, factor: float = 0.5) -> float:
    """Apply the G-STEP simple noise-adjustment formula to an estimated gain.

    Formula per arXiv 2605.00136 §3.2:
        adjusted = base × (1.0 - noise_level × factor)

    The default *factor* of 0.5 corresponds to the paper's moderate-noise
    regime.  Use a higher factor (e.g. 0.8) for high-noise environments
    where the tool's output is expected to be significantly degraded.

    Args:
        base_gain:   Nominal gain estimate (0.0–1.0) in a noiseless setting.
        noise_level: Current semantic noise level (0.0–1.0).
        factor:      Attenuation factor; default 0.5 per paper.

    Returns:
        Adjusted gain, clamped to [0.0, 1.0].
    """
    adjusted = base_gain * (1.0 - noise_level * factor)
    return max(0.0, min(1.0, adjusted))


class ExplainableDecider:
    """Produces an explained tool-use decision given context, gain, and noise.

    This is a standalone, stateless decider that clearly communicates *why*
    a particular intervention was chosen.  It complements the more elaborate
    ``GSTEPGate`` by offering a simpler API::

        decider = ExplainableDecider()
        decision = decider.decide(context="…", gain=0.6, noise=0.35)

    Each decision includes a structured *explanation* with the reasoning
    chain, applicable thresholds, and a confidence rating.
    """

    def __init__(
        self,
        cost_threshold: float = 0.25,
        noise_cap: float = 0.60,
    ) -> None:
        self._cost_threshold = cost_threshold
        self._noise_cap = noise_cap
        self._decisions: list[dict] = []

    # ── Public API ──────────────────────────────────────────────────────

    def decide(self, context: str, gain: float, noise: float) -> dict:
        """Return an explained decision.

        Args:
            context: The task/query context string (used for diagnostics).
            gain:    Estimated tool gain (0.0–1.0), *after* noise adjustment.
            noise:   Estimated semantic noise level (0.0–1.0).

        Returns:
            {
                "intervention": str,       # one of four G-STEP interventions
                "use_tool": bool,
                "reason": str,             # one-line summary
                "explanation": {           # structured explainability block
                    "gain": float,
                    "noise": float,
                    "cost_threshold": float,
                    "noise_cap": float,
                    "effective_margin": float,
                    "decision_rule": str,
                    "chain": [str, ...],   # step-by-step reasoning
                },
            }
        """
        adjusted_gain = noise_adjusted_gain(gain, noise)
        chain: list[str] = []

        chain.append(f"Context length: {len(context)} chars")
        chain.append(f"Base gain: {gain:.3f}, noise: {noise:.3f}")
        chain.append(f"Adjusted gain (× (1 - {noise:.2f} × 0.5)): {adjusted_gain:.3f}")

        # Rule 1: noise cap check
        if noise >= self._noise_cap:
            intervention = "skip_tool"
            reason = (
                f"Noise {noise:.2f} >= cap {self._noise_cap:.2f}: "
                f"semantic environment too degraded for reliable tool use"
            )
            chain.append(f"RULE 1 — noise ({noise:.2f}) >= cap ({self._noise_cap:.2f}) -> skip")
        elif adjusted_gain <= self._cost_threshold:
            intervention = "skip_tool"
            reason = (
                f"Noise-adjusted gain {adjusted_gain:.3f} <= cost threshold "
                f"{self._cost_threshold:.2f}: tool tax exceeds expected benefit"
            )
            chain.append(
                f"RULE 2 — adj. gain ({adjusted_gain:.3f}) <= threshold "
                f"({self._cost_threshold:.2f}) -> skip"
            )
        elif noise >= 0.35 and adjusted_gain > self._cost_threshold * 1.5:
            intervention = "use_with_caution"
            reason = (
                f"Moderate noise ({noise:.2f}) but gain ({adjusted_gain:.3f}) "
                f"comfortably exceeds threshold — using with caution"
            )
            chain.append(f"RULE 3 — moderate noise, sufficient margin -> use_with_caution")
        else:
            intervention = "use_tool"
            reason = (
                f"Low noise ({noise:.2f}), gain ({adjusted_gain:.3f}) "
                f"> threshold ({self._cost_threshold:.2f}) — proceeding with tool"
            )
            chain.append(f"RULE 4 — low noise, gain > threshold -> use_tool")

        margin = adjusted_gain - self._cost_threshold

        explanation = {
            "gain": round(adjusted_gain, 4),
            "noise": round(noise, 4),
            "cost_threshold": self._cost_threshold,
            "noise_cap": self._noise_cap,
            "effective_margin": round(margin, 4),
            "decision_rule": intervention,
            "chain": chain,
        }

        result = {
            "intervention": intervention,
            "use_tool": intervention in ("use_tool", "use_with_caution"),
            "reason": reason,
            "explanation": explanation,
        }

        self._decisions.append(result)
        return result

    def get_stats(self) -> dict:
        if not self._decisions:
            return {"total_decisions": 0}
        interventions: dict[str, int] = {}
        for d in self._decisions:
            interventions[d["intervention"]] = interventions.get(d["intervention"], 0) + 1
        return {
            "total_decisions": len(self._decisions),
            "interventions": interventions,
        }


# ======================================================================
# SemanticNoiseModeler — 估计当前上下文的语义噪声水平
# ======================================================================

class SemanticNoiseModeler:
    """估计当前上下文的语义噪声水平。

    G-STEP 论文定义的语义噪声维度:
    - ambiguity (歧义): 模糊、不确定的表达
    - incomplete (不完整): 信息缺失
    - conflicting (矛盾): 互相矛盾���信号
    - noise (干扰): 无关、偏离主题的内容

    输出: 综合噪声分数 (0.0 ~ 1.0) 及各维度细分。
    """

    def __init__(self):
        self._analyses: list[dict] = []

    def estimate(self, task: str, context: str = "") -> dict:
        """估计给定任务/上下文的语义噪声水平。

        Args:
            task: 任务描述
            context: 可选的额外上下文信息

        Returns:
            {
                "noise_score": float,       # 0.0 ~ 1.0, 综合噪声
                "dimensions": {             # 各维度噪声
                    "ambiguity": float,
                    "incomplete": float,
                    "conflicting": float,
                    "noise": float,
                },
                "confidence": float,        # 估计置信度
                "details": str,             # 简要说明
            }
        """
        combined_text = task + " " + context
        low = combined_text.lower()
        words = low.split()
        n_words = max(len(words), 1)

        dim_scores = {}
        dim_details = {}

        for dim, config in _NOISE_DIMENSIONS.items():
            matches = 0
            matched_keywords = []
            for kw in config["keywords"]:
                if kw in low:
                    # 精确匹配加分
                    matches += low.count(kw)
                    matched_keywords.append(kw)

            # 标准化为 0~1 分数
            raw_score = min(1.0, matches / max(n_words * 0.05, 1))
            # 加权
            weighted_score = min(1.0, raw_score * 2.0)

            dim_scores[dim] = round(weighted_score, 3)
            if matched_keywords:
                dim_details[dim] = matched_keywords[:5]  # 记录前5个匹配

        # 综合噪声 = 加权平均
        total_weight = sum(c["weight"] for c in _NOISE_DIMENSIONS.values())
        noise_score = sum(
            dim_scores[dim] * _NOISE_DIMENSIONS[dim]["weight"]
            for dim in _NOISE_DIMENSIONS
        ) / total_weight

        noise_score = min(1.0, noise_score)

        # 置信度：分析的文本长度越长，置信度越高
        confidence = min(1.0, n_words / 100.0)

        # 细节描述
        high_dimensions = [d for d, s in dim_scores.items() if s > 0.3]
        if high_dimensions:
            details = f"Semantic noise detected ({', '.join(high_dimensions)}"
            if dim_details:
                example_kws = []
                for d in high_dimensions:
                    if d in dim_details:
                        example_kws.extend(dim_details[d][:2])
                if example_kws:
                    details += f": {', '.join(example_kws)}"
            details += ")"
        else:
            details = "Low semantic noise"

        result = {
            "noise_score": round(noise_score, 3),
            "dimensions": dim_scores,
            "confidence": round(confidence, 3),
            "details": details,
        }

        self._analyses.append(result)
        return result

    def adapt_threshold(self, base_threshold: float, noise_score: float) -> float:
        """根据噪声水平调整决策阈值。

        G-STEP 发现：噪声越高，越需要保守（更高阈值）。
        使用指数缩放: adjusted = base * (1 + noise^2)
        """
        return base_threshold * (1.0 + noise_score ** 2)

    def get_stats(self) -> dict:
        if not self._analyses:
            return {"total_analyses": 0}
        avg_noise = sum(a["noise_score"] for a in self._analyses) / len(self._analyses)
        return {
            "total_analyses": len(self._analyses),
            "avg_noise_score": round(avg_noise, 3),
        }


# ======================================================================
# GainEstimator — 动态增益估计，随语义噪声衰减
# ======================================================================

class GainEstimator:
    """动态增益估计，增益值随语义噪声线性/非线性衰减。

    G-STEP 核心发现: 在语义噪声下，工具使用的实际收益低于名义收益。
    噪声会"模糊"工具的预期输出，导致:
    - 信息增益下降 (工具输出可能自带噪声)
    - 执行精度下降 (参数可能被误解释)
    - 整合成本上升 (需要额外验证步骤)

    增益调整公式: effective_gain = base_gain * (1 - noise_penalty)
    其中 noise_penalty = noise_score * attenuation_factor
    """

    def __init__(self, base_gains: dict | None = None):
        self._base_gains = base_gains or {
            "simple": 0.20,
            "moderate": 0.50,
            "complex": 0.70,
        }
        self._estimates: list[dict] = []

    def estimate(self, task: str, tool_info: dict | None = None,
                 noise_result: dict | None = None) -> dict:
        """估���工具使用的有效增益。

        Args:
            task: 任务描述
            tool_info: 可选，工具特定信息（含 "gain" 键）
            noise_result: 可选，语义噪声分析结果

        Returns:
            {
                "base_gain": float,
                "effective_gain": float,    # 经噪声调整后的增益
                "noise_penalty": float,     # 噪声惩罚值
                "confidence": float,
                "method": str,              # 估计方法描述
            }
        """
        low = task.lower()

        # 基础增益（无噪声时）
        if tool_info and "gain" in tool_info:
            base_gain = tool_info["gain"]
            method = "tool-specific gain"
        elif any(t in low for t in _COMPLEX_TASKS):
            base_gain = self._base_gains["complex"]
            method = "complex task heuristic"
        elif any(t in low for t in _MODERATE_TASKS):
            base_gain = self._base_gains["moderate"]
            method = "moderate task heuristic"
        else:
            base_gain = self._base_gains["simple"]
            method = "simple task heuristic"

        # 噪声调整
        noise_score = noise_result["noise_score"] if noise_result else 0.0

        # G-STEP 噪声衰减公式: 有效增益 = 基础增益 × (1 - 噪声² × 衰减因子)
        attenuation_factor = 0.85  # G-STEP 论文中使用的典型值
        noise_penalty = noise_score ** 2 * attenuation_factor
        effective_gain = base_gain * (1.0 - noise_penalty)
        effective_gain = max(0.0, effective_gain)

        # 置信度: 噪声越低，对增益估计越有信心
        confidence = max(0.1, 1.0 - noise_score * 1.5)

        result = {
            "base_gain": round(base_gain, 4),
            "effective_gain": round(effective_gain, 4),
            "noise_penalty": round(noise_penalty, 4),
            "confidence": round(confidence, 3),
            "method": method,
        }

        self._estimates.append(result)
        return result

    def get_stats(self) -> dict:
        if not self._estimates:
            return {"total_estimates": 0}
        avg_eff_gain = sum(e["effective_gain"] for e in self._estimates) / len(self._estimates)
        avg_penalty = sum(e["noise_penalty"] for e in self._estimates) / len(self._estimates)
        return {
            "total_estimates": len(self._estimates),
            "avg_effective_gain": round(avg_eff_gain, 4),
            "avg_noise_penalty": round(avg_penalty, 4),
        }


# ======================================================================
# GSTEPGate — 完整的因子化干预决策
# ======================================================================

class GSTEPGate:
    """G-STEP 因子化干预框架的完整实现。

    决策流程:
    1. 估计语义噪声水平 (SemanticNoiseModeler)
    2. 估计噪声调整后的增益 (GainEstimator)
    3. 计算工具使用总成本 (继承 ToolTaxGate 的 3 组件模型)
    4. 比较 adjusted_gain > total_cost × (1 + noise_margin)
    5. 输出干预决策

    因子化干预: 当噪声过高时，可以选择:
    - "use_tool": 正常使用工具
    - "skip_tool": 跳过工具，使用原生 CoT
    - "defer": 推迟决策（需要更多信息）
    - "use_with_caution": 使用工具但附加验证
    """

    # 噪声分界值
    NOISE_LOW = 0.20
    NOISE_MEDIUM = 0.45
    NOISE_HIGH = 0.70

    def __init__(self):
        self.noise_modeler = SemanticNoiseModeler()
        self.gain_estimator = GainEstimator()
        self._decisions: list[dict] = []
        self._total = 0
        self._tools_used = 0

    def decide(self, task: str, tool_info: dict | None = None,
               context: str = "") -> dict:
        """G-STEP 因子化干预决策。

        Args:
            task: 任务描述
            tool_info: 可选，工具信息 (含 "cost", "gain")
            context: 额外上下文（用于噪声分析）

        Returns:
            {
                "intervention": str,         # "use_tool", "skip_tool", "defer", "use_with_caution"
                "use_tool": bool,            # 兼容原有接口
                "reason": str,
                "estimated_cost": float,
                "estimated_gain": float,
                "noise_analysis": dict,
                "gain_analysis": dict,
            }
        """
        self._total += 1
        low = task.lower()

        # 1. 语义噪声分析
        noise_result = self.noise_modeler.estimate(task, context)
        noise_score = noise_result["noise_score"]

        # 2. 成本计算（继承原有结构）
        prompt_cost = len(task) / 100.0 * 0.01
        protocol_cost = _PROTOCOL_OVERHEAD
        execution_cost = _EXECUTION_GATE
        if tool_info:
            execution_cost += tool_info.get("cost", 0.0)
        total_cost = prompt_cost + protocol_cost + execution_cost

        # 3. 噪声调整后的增益
        gain_result = self.gain_estimator.estimate(task, tool_info, noise_result)
        effective_gain = gain_result["effective_gain"]

        # 4. 噪声边际: 噪声越高，需要的增益边际越大
        # G-STEP: adjusted_cost = cost × (1 + noise^1.5)
        noise_margin = 1.0 + (noise_score ** 1.5) * 0.5
        adjusted_cost = total_cost * noise_margin

        # 5. 因子化干预决策
        if noise_score >= self.NOISE_HIGH:
            # 高噪声 → 跳过或推迟
            if effective_gain <= adjusted_cost * 1.5:
                intervention = "skip_tool"
                use_tool = False
                reason = (f"High semantic noise ({noise_score:.2f}) degrades gain "
                          f"({effective_gain:.3f}) below adjusted cost ({adjusted_cost:.3f})")
            else:
                intervention = "defer"
                use_tool = False
                reason = (f"High noise ({noise_score:.2f}) — deferring decision, "
                          f"need more context to confirm tool benefit")

        elif noise_score >= self.NOISE_MEDIUM:
            # 中等噪声 → 谨慎使用
            if effective_gain > adjusted_cost:
                intervention = "use_with_caution"
                use_tool = True
                reason = (f"Medium noise ({noise_score:.2f}) — gain ({effective_gain:.3f}) "
                          f"> adjusted cost ({adjusted_cost:.3f}), using with caution")
            else:
                intervention = "skip_tool"
                use_tool = False
                reason = (f"Medium noise ({noise_score:.2f}) — gain ({effective_gain:.3f}) "
                          f"≤ adjusted cost ({adjusted_cost:.3f})")
        else:
            # 低噪声 → 正常决策
            if effective_gain > total_cost:
                intervention = "use_tool"
                use_tool = True
                reason = (f"Low noise ({noise_score:.2f}) — gain ({effective_gain:.3f}) "
                          f"> cost ({total_cost:.3f})")
            else:
                intervention = "skip_tool"
                use_tool = False
                reason = (f"Low noise ({noise_score:.2f}) — gain ({effective_gain:.3f}) "
                          f"≤ cost ({total_cost:.3f})")

        result = {
            "intervention": intervention,
            "use_tool": use_tool,
            "reason": reason,
            "estimated_cost": round(total_cost, 4),
            "adjusted_cost": round(adjusted_cost, 4),
            "estimated_gain": round(effective_gain, 4),
            "noise_analysis": noise_result,
            "gain_analysis": gain_result,
        }

        self._decisions.append(result)
        if use_tool:
            self._tools_used += 1
        return result

    def get_stats(self) -> dict:
        interventions = {}
        for d in self._decisions:
            i_type = d.get("intervention", "unknown")
            interventions[i_type] = interventions.get(i_type, 0) + 1

        avg_cost = 0.0
        avg_gain = 0.0
        if self._decisions:
            avg_cost = sum(d["estimated_cost"] for d in self._decisions) / len(self._decisions)
            avg_gain = sum(d["estimated_gain"] for d in self._decisions) / len(self._decisions)

        return {
            "total": self._total,
            "tool_use_rate": round(self._tools_used / max(self._total, 1), 4),
            "avg_cost": round(avg_cost, 4),
            "avg_gain": round(avg_gain, 4),
            "interventions": interventions,
            "noise_stats": self.noise_modeler.get_stats(),
        }


# ======================================================================
# ToolTaxGate — 扩展版，集成 G-STEP 组件
# ======================================================================

class ToolTaxGate:
    """G-STEP 推理时门控（原有接口兼容）。

    在原有 3 组件成本结构基础上，增加:
    - SemanticNoiseModeler: 语义噪声水平估计
    - GainEstimator: 噪声调整增益估计
    - GSTEPGate: 完整的因子化干预决策框架

    原有接口 `decide()` 现在内部使用 G-STEP 逻辑，但保持输出格式兼容。
    """

    def __init__(self, enable_gstep: bool = True):
        self.enable_gstep = enable_gstep
        self._decisions: list[dict] = []
        self._total = 0
        self._tools_used = 0
        self.gstep = GSTEPGate() if enable_gstep else None
        self.noise_estimator = SemanticNoiseEstimator()
        self.explainable_decider = ExplainableDecider()

    def decide(self, task: str, tool_info: dict | None = None) -> dict:
        """决定是否使用工具。

        当 enable_gstep=True 时，使用完整的 G-STEP 因子化干预框架。
        当 enable_gstep=False 时，使用原有的简单关键字匹配。

        Args:
            task: 任务描述
            tool_info: 工具信息，含 {"cost": float, "gain": float, "protocol": str}

        Returns:
            {"use_tool": bool, "reason": str, "estimated_cost": float, "estimated_gain": float}
            以及 gstep 扩展信息
        """
        self._total += 1

        if self.enable_gstep and self.gstep:
            result = self.gstep.decide(task, tool_info)
            # 简化为兼容原有接口
            simplified = {
                "use_tool": result["use_tool"],
                "reason": result["reason"],
                "estimated_cost": result["estimated_cost"],
                "estimated_gain": result["estimated_gain"],
                "intervention": result["intervention"],
                "noise_score": result["noise_analysis"]["noise_score"],
            }
            self._decisions.append(simplified)
            if result["use_tool"]:
                self._tools_used += 1
            return simplified

        # 原有逻辑（当 gstep 禁用时的 fallback）
        low = task.lower()

        prompt_cost = len(task) / 100.0 * 0.01
        protocol_cost = _PROTOCOL_OVERHEAD
        execution_cost = _EXECUTION_GATE
        if tool_info:
            execution_cost += tool_info.get("cost", 0.0)
        total_cost = prompt_cost + protocol_cost + execution_cost

        if any(t in low for t in _COMPLEX_TASKS):
            base_gain = 0.7
            reason = "Complex task — tool likely beneficial"
            use_tool = True
        elif any(t in low for t in _MODERATE_TASKS):
            base_gain = 0.5
            reason = "Moderate task — tool may help"
            use_tool = True
        else:
            base_gain = 0.2
            reason = "Simple task — native CoT sufficient"
            use_tool = False

        if tool_info and "gain" in tool_info:
            base_gain = tool_info["gain"]

        # Apply noise-adjusted gain in the fallback path too
        noise_est = self.noise_estimator.estimate(task)
        noise_level = noise_est["noise_score"]
        estimated_gain = noise_adjusted_gain(base_gain, noise_level)
        reason_extra = f" (noise={noise_level:.2f}, adj_gain={estimated_gain:.3f}"

        if estimated_gain <= total_cost:
            use_tool = False
            reason += f" (tool tax > gain; noise-adjusted)"
        else:
            reason += reason_extra + " > cost)"

        result = {
            "use_tool": use_tool,
            "reason": reason,
            "estimated_cost": round(total_cost, 4),
            "estimated_gain": round(estimated_gain, 4),
            "noise_analysis": noise_est,
        }
        # Also produce an explainable decision
        xd = self.explainable_decider.decide(task, estimated_gain, noise_level)
        result["explanation"] = xd["explanation"]
        self._decisions.append(result)
        if use_tool:
            self._tools_used += 1
        return result

    def get_stats(self) -> dict:
        gstep_stats = {}
        if self.enable_gstep and self.gstep:
            gstep_stats = self.gstep.get_stats()
        return {
            "total": self._total,
            "tool_use_rate": round(self._tools_used / max(self._total, 1), 4),
            "avg_cost": round(sum(d["estimated_cost"] for d in self._decisions) / max(len(self._decisions), 1), 4),
            "gstep_enabled": self.enable_gstep,
            "gstep": gstep_stats,
        }
