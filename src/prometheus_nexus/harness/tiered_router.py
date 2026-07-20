"""TieredRouter — task router that classifies input tasks into capability tiers.

Reference: AgentFloor (arXiv 2605.00334) describes a 30-task/6-tier benchmark
for evaluating 16 open-source models on a capability ladder.

IMPORTANT: This module is a TASK ROUTER, NOT the AgentFloor benchmark itself.
It routes tasks to capability tiers so the system can select an appropriate
backend model or processing strategy. It does NOT implement the AgentFloor
evaluation protocol.

Tiers (6):
  0. instruction_following -- simple instruction following (no tools)
  1. simple_tool         -- single tool call
  2. multi_tool          -- multi-tool collaboration
  3. coordination        -- inter-model / inter-system coordination
  4. planning            -- multi-step planning with dependencies
  5. long_horizon        -- long-running / sustained tasks

Classes:
  - TierMapper          -- tier definitions and feature vectors
  - TaskClassifier      -- heuristic + semantic task classification
  - CapabilityTracker   -- per-tier usage tracking and success-rate stats
  - TieredRouter        -- unified interface: route + track + stats

For the REAL AgentFloor benchmark, see: https://arxiv.org/abs/2605.00334
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# ======================================================================
# 6 层级定义
# ======================================================================

TIER_DEFINITIONS = {
    "instruction_following": {
        "index": 0,
        "description": "Simple instruction following, no tools needed",
        "keywords": {"greet", "echo", "hello", "hi", "reply", "format", "convert",
                     "today", "time", "weather", "math", "translate", "simple"},
        "model_capability": "Basic text generation, no tool use required",
        "example_tasks": ["Say hello", "What time is it?", "Format this text"],
    },
    "simple_tool": {
        "index": 1,
        "description": "Single tool call with simple parameters",
        "keywords": {"search", "lookup", "read", "find", "get", "fetch",
                     "calculate", "check", "compute", "query", "call"},
        "model_capability": "Single tool invocation, basic parameter passing",
        "example_tasks": ["Search for X", "Read file Y", "Calculate Z"],
    },
    "multi_tool": {
        "index": 2,
        "description": "Multiple coordinated tool calls",
        "keywords": {"compare", "analyze", "aggregate", "combine", "cross-reference",
                     "pipeline", "workflow", "multi-step", "sequential", "both",
                     "and also", "then", "after that", "simultaneous"},
        "model_capability": "Sequential/parallel tool use, result chaining",
        "example_tasks": ["Search X then summarize results", "Compare A and B"],
    },
    "coordination": {
        "index": 3,
        "description": "Inter-model or inter-system coordination",
        "keywords": {"delegate", "coordinate", "orchestrate", "assign", "distribute",
                     "team", "collaborate", "sync", "handoff", "parallel",
                     "expert", "specialist", "agent", "sub-task", "split"},
        "model_capability": "Task decomposition, delegation, result merging",
        "example_tasks": ["Coordinate data collection across sources",
                          "Assign sub-tasks to specialized agents"],
    },
    "planning": {
        "index": 4,
        "description": "Multi-step planning with dependencies",
        "keywords": {"plan", "strategy", "roadmap", "timeline", "schedule",
                     "milestone", "phase", "step-by-step", "blueprint", "design",
                     "architecture", "framework", "approach", "methodology"},
        "model_capability": "Dependency tracking, contingency planning, optimization",
        "example_tasks": ["Plan a software release", "Design system architecture"],
    },
    "long_horizon": {
        "index": 5,
        "description": "Long-term tasks requiring sustained context",
        "keywords": {"long-term", "ongoing", "continuous", "monitor", "watch",
                     "track", "evolve", "iterate", "improve gradually",
                     "sustained", "long-running", "background", "persistent",
                     "cumulative", "progressive", "over time"},
        "model_capability": "Context retention, progress tracking, adaptive planning",
        "example_tasks": ["Monitor system health over 24h",
                          "Gradually improve codebase over weeks"],
    },
}

_TIER_ORDER = [
    "instruction_following",
    "simple_tool",
    "multi_tool",
    "coordination",
    "planning",
    "long_horizon",
]


# ======================================================================
# TierMapper — 层级定义和特征向量
# ======================================================================

class TierMapper:
    """Maps tier names to their definitions and feature vectors.

    Provides programmatic access to tier metadata, index lookup,
    and feature vectors for downstream routing logic.
    """

    def __init__(self):
        self._tiers = dict(TIER_DEFINITIONS)
        self._order = list(_TIER_ORDER)

    @property
    def tiers(self) -> dict:
        """All tier definitions (read-only view)."""
        return dict(self._tiers)

    @property
    def order(self) -> list[str]:
        """Tier names in ascending order of capability."""
        return list(self._order)

    @property
    def count(self) -> int:
        """Number of tiers (6)."""
        return len(self._order)

    def get(self, name: str) -> dict | None:
        """Get a tier definition by name, or None if not found."""
        return self._tiers.get(name)

    def index_of(self, name: str) -> int | None:
        """Get the index (0-5) of a tier, or None if not found."""
        t = self._tiers.get(name)
        return t["index"] if t else None

    def name_of(self, index: int) -> str | None:
        """Get the tier name for a given index (0-5), or None."""
        for name, defn in self._tiers.items():
            if defn["index"] == index:
                return name
        return None

    def keywords_for(self, name: str) -> set[str]:
        """Get the keyword set for a tier, or empty set."""
        t = self._tiers.get(name)
        return set(t["keywords"]) if t else set()

    def feature_vector(self, name: str) -> dict | None:
        """Get a feature vector dict for a tier, or None."""
        t = self._tiers.get(name)
        if not t:
            return None
        return {
            "index": t["index"],
            "keywords": sorted(t["keywords"]),
            "description": t["description"],
        }


# ======================================================================
# TaskClassifier — 基于语义分析和启发式的任务分类
# ======================================================================

class TaskClassifier:
    """将输入任务分类到 6 个能力层级之一。

    使用多种启发式:
    1. 关键词匹配（加权）
    2. 句法分析（命令长度、工具数量提示）
    3. 上下文线索（多步、协调等）
    4. 任务复杂度估算（信息论）
    """

    def __init__(self):
        self._classifications: list[dict] = []

    def classify(self, task: str, context: str = "") -> dict:
        """分类任务到能力层级。

        Args:
            task: 任务描述文本
            context: 可选，额外上下文

        Returns:
            {
                "tier": str,                # 分类结果层级
                "tier_index": int,          # 层级索引 (0~5)
                "confidence": float,        # 分类置信度 0~1
                "scores": dict,             # 各层级分数
                "features": dict,           # 提取的特征
                "reason": str,              # 分类理由
            }
        """
        low = task.lower()
        combined = low + " " + context.lower()
        words = combined.split()
        n_words = len(words)

        # --- 特征提取 ---

        features = {
            "word_count": n_words,
            "has_question": "?" in task,
            "has_list": bool(re.search(r'(?:^|\n)\s*(?:[-*\d.])', task)),
            "has_multi_step_indicators": 0,
            "has_coordination_indicators": 0,
            "has_long_horizon_indicators": 0,
            "tool_count_estimate": 0,
            "sentence_count": len(re.split(r'[.!?\n]', task)),
        }

        # 多步指示器
        multi_step_words = {"then", "after", "subsequently", "next", "step",
                           "phase", "stage", "first", "second", "finally",
                           "once", "when done", "proceed to", "followed by"}
        features["has_multi_step_indicators"] = sum(
            1 for w in multi_step_words if w in low
        )

        # 协调指示器
        coordination_words = {"delegate", "coordinate", "assign", "team",
                             "expert", "specialist", "together", "collaborate",
                             "hand off", "sync", "merge", "combine results"}
        features["has_coordination_indicators"] = sum(
            1 for w in coordination_words if w in low
        )

        # 长期指示器
        long_horizon_words = {"monitor", "track", "ongoing", "continuous",
                             "over time", "long term", "sustained", "watch",
                             "persistent", "background", "cumulative"}
        features["has_long_horizon_indicators"] = sum(
            1 for w in long_horizon_words if w in low
        )

        # 工具数量估计（基于动词和命名实体）
        tool_verbs = {"search", "read", "write", "create", "delete", "update",
                     "call", "fetch", "compute", "execute", "run", "send",
                     "get", "post", "list", "find", "open", "close"}
        features["tool_count_estimate"] = sum(
            1 for w in low.split() if w in tool_verbs
        )

        # --- 层级评分 ---

        scores = {}
        for tier_name, tier_def in TIER_DEFINITIONS.items():
            score = 0.0

            # 关键词匹配
            keyword_matches = sum(1 for kw in tier_def["keywords"] if kw in low)
            score += keyword_matches * 0.15

            # 多步指示 → 较高层级加分
            if tier_name == "multi_tool":
                score += features["has_multi_step_indicators"] * 0.12
            if tier_name == "coordination":
                score += features["has_coordination_indicators"] * 0.18
            if tier_name == "long_horizon":
                score += features["has_long_horizon_indicators"] * 0.20
            if tier_name == "planning":
                # 多步 + 协调 → 规划
                if features["has_multi_step_indicators"] > 0 and features["has_coordination_indicators"] > 0:
                    score += 0.25

            # 工具数量估计 → simple_tool/multi_tool
            if tier_name == "simple_tool" and features["tool_count_estimate"] == 1:
                score += 0.20
            if tier_name == "multi_tool" and features["tool_count_estimate"] >= 2:
                score += 0.25

            # 简单任务：短 + 低工具 + 无多步
            if tier_name == "instruction_following":
                if n_words < 15 and features["tool_count_estimate"] == 0:
                    score += 0.30
                if features["has_multi_step_indicators"] == 0 and features["has_coordination_indicators"] == 0:
                    score += 0.10

            # 长文本 → 更复杂层级加分
            if n_words > 50:
                if tier_name in ("planning", "long_horizon"):
                    score += 0.15

            scores[tier_name] = round(score, 3)

        # --- 选择最佳层级 ---
        # 需要至少 0.15 分才能匹配，否则回退到 instruction_following
        min_score = 0.15
        best_tier = "instruction_following"
        best_score = scores["instruction_following"]

        for tier_name in _TIER_ORDER:
            if scores[tier_name] > best_score:
                best_score = scores[tier_name]
                best_tier = tier_name

        # 置信度: 基于最佳和次佳的差距
        sorted_scores = sorted(scores.values(), reverse=True)
        if len(sorted_scores) >= 2:
            gap = sorted_scores[0] - sorted_scores[1]
            confidence = min(1.0, gap * 2.0 + 0.3)
        else:
            confidence = 0.5

        # 分类理由
        tier_def = TIER_DEFINITIONS[best_tier]
        reason = (f"Tier '{best_tier}' (idx={tier_def['index']}): "
                  f"score={best_score:.2f}, confidence={confidence:.2f}. "
                  f"{tier_def['description']}")

        result = {
            "tier": best_tier,
            "tier_index": tier_def["index"],
            "confidence": round(confidence, 3),
            "scores": scores,
            "features": features,
            "reason": reason,
        }

        self._classifications.append(result)
        return result

    def classify_batch(self, tasks: list[str]) -> list[dict]:
        return [self.classify(t) for t in tasks]

    def get_stats(self) -> dict:
        if not self._classifications:
            return {"total_classifications": 0}
        distribution = {}
        for c in self._classifications:
            t = c["tier"]
            distribution[t] = distribution.get(t, 0) + 1
        avg_conf = sum(c["confidence"] for c in self._classifications) / len(self._classifications)
        return {
            "total_classifications": len(self._classifications),
            "distribution": distribution,
            "avg_confidence": round(avg_conf, 3),
        }


# ======================================================================
# CapabilityTracker — 层级使用跟踪和成功率统计
# ======================================================================

class CapabilityTracker:
    """跟踪每个层级的尝试次数、成功率和失败原因。

    对应 AgentFloor 中评估模型能力的概念 — 跟踪哪些层级被尝试过、
    成功率和失败模式，为未来的模型选择提供数据支持。
    """

    def __init__(self):
        self._records: list[dict] = []
        self._tier_stats: dict[str, dict] = {
            t: {"attempts": 0, "successes": 0, "failures": 0,
                "failure_reasons": [], "avg_confidence": 0.0}
            for t in _TIER_ORDER
        }

    def record_outcome(self, tier: str, success: bool,
                       confidence: float = 0.0,
                       failure_reason: str = "") -> None:
        """记录一次层级路由的结果。

        Args:
            tier: 层级名
            success: 是否成功
            confidence: 路由置信度
            failure_reason: 失败原因（可选）
        """
        if tier not in self._tier_stats:
            tier = "instruction_following"  # fallback

        self._tier_stats[tier]["attempts"] += 1
        if success:
            self._tier_stats[tier]["successes"] += 1
        else:
            self._tier_stats[tier]["failures"] += 1
            if failure_reason:
                self._tier_stats[tier]["failure_reasons"].append(failure_reason)

        # 更新平均置信度
        old_avg = self._tier_stats[tier]["avg_confidence"]
        n = self._tier_stats[tier]["attempts"]
        self._tier_stats[tier]["avg_confidence"] = (
            (old_avg * (n - 1) + confidence) / n
        )

        self._records.append({
            "tier": tier,
            "success": success,
            "confidence": confidence,
            "failure_reason": failure_reason,
            "timestamp": time.time(),
        })

    def get_tier_stats(self, tier: str | None = None) -> dict:
        """获取层级统计。

        Args:
            tier: 指定层级，None 返回全部

        Returns:
            {
                "tier_name": {
                    "attempts": int,
                    "successes": int,
                    "failures": int,
                    "success_rate": float,
                    "failure_reasons": list[str],
                    "avg_confidence": float,
                }
            }
        """
        if tier:
            if tier not in self._tier_stats:
                return {}
            stats = dict(self._tier_stats[tier])
            stats["success_rate"] = round(
                stats["successes"] / max(stats["attempts"], 1), 3
            )
            return {tier: stats}

        result = {}
        for t, s in self._tier_stats.items():
            s = dict(s)
            s["success_rate"] = round(
                s["successes"] / max(s["attempts"], 1), 3
            )
            result[t] = s
        return result

    def get_overall_stats(self) -> dict:
        total = sum(s["attempts"] for s in self._tier_stats.values())
        successes = sum(s["successes"] for s in self._tier_stats.values())
        return {
            "total_attempts": total,
            "total_successes": successes,
            "overall_success_rate": round(successes / max(total, 1), 3),
            "tiers_attempted": sum(1 for s in self._tier_stats.values() if s["attempts"] > 0),
            "tiers_with_high_success": sum(
                1 for s in self._tier_stats.values()
                if s["attempts"] > 0 and (s["successes"] / max(s["attempts"], 1)) > 0.8
            ),
        }

    def get_failure_patterns(self) -> dict:
        """总结常见失败模式。"""
        all_reasons = []
        for t, s in self._tier_stats.items():
            all_reasons.extend(s["failure_reasons"])

        if not all_reasons:
            return {}

        # 简单频率统计
        from collections import Counter
        reason_counts = Counter(all_reasons)
        top_reasons = reason_counts.most_common(5)
        return {
            "total_failures": len(all_reasons),
            "top_reasons": [
                {"reason": r, "count": c, "pct": round(c / len(all_reasons) * 100, 1)}
                for r, c in top_reasons
            ],
        }

    def reset(self) -> None:
        """重置所有跟踪数据到初始状态。"""
        self._records.clear()
        self._tier_stats = {
            t: {"attempts": 0, "successes": 0, "failures": 0,
                "failure_reasons": [], "avg_confidence": 0.0}
            for t in _TIER_ORDER
        }

    def to_dict(self) -> dict:
        """Serialize tracker state to a JSON-compatible dict."""
        return {
            "records": list(self._records),
            "tier_stats": self._tier_stats,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CapabilityTracker:
        """Restore tracker state from a dict produced by to_dict()."""
        tracker = cls()
        tracker._records = list(data.get("records", []))
        tier_data = data.get("tier_stats", {})
        for t, s in tier_data.items():
            if t in tracker._tier_stats:
                tracker._tier_stats[t] = dict(s)
        return tracker
# ======================================================================
# AgentFloor Benchmark Evaluator (arXiv 2605.00334)
# 30-task/6-tier evaluation protocol matching the paper
# ======================================================================

class AgentFloorEvaluator:
    """AgentFloor benchmark: 30-task/6-tier evaluation of model capabilities.

    Implements the evaluation protocol from arXiv 2605.00334:
    - 6 capability tiers (0-5), 5 tasks per tier = 30 tasks total
    - Each task is classified to the correct tier by TaskClassifier
    - Evaluates model success rate per tier and overall capability ladder

    Usage:
        evaluator = AgentFloorEvaluator()
        result = evaluator.evaluate_all(model_evaluator_fn)
        # model_evaluator_fn(task, tier) -> {"success": bool, "output": str}
        print(result["tier_results"])
        print(f"Overall: {result['overall_success_rate']:.1%}")
    """

    TIER_TASKS = {
        "instruction_following": [
            "Say hello", "What time is it?", "Convert 25°C to Fahrenheit",
            "Format this list into bullet points", "Reverse the string 'hello'",
        ],
        "simple_tool": [
            "Search for the capital of France",
            "Calculate the square root of 144",
            "Look up the definition of photosynthesis",
            "Find today's date",
            "Translate 'good morning' to Spanish",
        ],
        "multi_tool": [
            "Search for weather in Tokyo then convert to Celsius",
            "Cross-reference population density with area size for 3 countries",
            "Analyze the sentiment of a text and summarize key themes",
            "Compare economic growth rates of US, China, and India",
            "Fetch stock prices and calculate the moving average",
        ],
        "coordination": [
            "Coordinate data collection from 3 web sources and merge results",
            "Delegate sub-tasks to specialized agents and synthesize findings",
            "Assign research topics to 2 experts and aggregate their reports",
            "Hand off intermediate results between search and analysis tools",
            "Synchronize parallel data streams and detect inconsistencies",
        ],
        "planning": [
            "Plan a 3-phase software release with dependencies and milestones",
            "Design a system architecture with load balancing and failover",
            "Create a roadmap for migrating from monolith to microservices",
            "Schedule a deployment pipeline with CI/CD stages and rollback plan",
            "Develop a testing strategy with unit, integration, and e2e phases",
        ],
        "long_horizon": [
            "Monitor system health metrics over 24 hours and alert on anomalies",
            "Track codebase quality metrics over 2 weeks and suggest improvements",
            "Evolve a prompt strategy gradually based on user interaction feedback",
            "Maintain persistent context for a multi-day research project",
            "Accumulate and refine knowledge from daily user interactions",
        ],
    }

    def __init__(self):
        self._classifier = TaskClassifier()
        self._tier_results: dict[str, dict] = {}
        self._eval_log: list[dict] = []

    def get_benchmark_tasks(self) -> dict[str, list[str]]:
        """Return the 30-task AgentFloor benchmark suite."""
        return dict(self.TIER_TASKS)

    def evaluate(self, tier: str, evaluator_fn: callable) -> dict:
        """Evaluate a model on one tier (5 tasks).

        Args:
            tier: Tier name from TIER_TASKS.
            evaluator_fn: callable(task: str, tier: str) -> {"success": bool}

        Returns:
            {"tier": str, "score": float (0-5), "tasks": list}
        """
        tasks = self.TIER_TASKS.get(tier, [])
        results = []
        successes = 0
        for task in tasks:
            try:
                output = evaluator_fn(task, tier)
                success = output.get("success", False)
            except Exception:
                logger.warning("TieredRouter: task evaluation failed, marking as unsuccessful")
                success = False
            results.append({"task": task, "success": success})
            if success:
                successes += 1

        tier_result = {
            "tier": tier,
            "score": successes,
            "max_score": len(tasks),
            "success_rate": successes / max(len(tasks), 1),
            "tasks": results,
        }
        self._tier_results[tier] = tier_result
        self._eval_log.append(tier_result)
        return tier_result

    def evaluate_all(self, evaluator_fn: callable) -> dict:
        """Run the full 30-task AgentFloor benchmark.

        Args:
            evaluator_fn: callable(task, tier) -> {"success": bool, ...}

        Returns:
            {"tier_results": {tier: dict}, "overall_success_rate": float,
             "capability_ladder": int, "total_tasks": int, "total_successes": int}
        """
        self._tier_results = {}
        for tier in _TIER_ORDER:
            self.evaluate(tier, evaluator_fn)

        total = sum(r["max_score"] for r in self._tier_results.values())
        successes = sum(r["score"] for r in self._tier_results.values())

        # Capability ladder: highest tier with >= 60% success rate
        ladder = -1
        for i, tier in enumerate(_TIER_ORDER):
            tr = self._tier_results.get(tier, {})
            if tr.get("success_rate", 0) >= 0.6:
                ladder = i

        return {
            "tier_results": dict(self._tier_results),
            "overall_success_rate": successes / max(total, 1),
            "capability_ladder": ladder,
            "capability_tier": _TIER_ORDER[ladder] if ladder >= 0 else "none",
            "total_tasks": total,
            "total_successes": successes,
        }

    def get_stats(self) -> dict:
        return {
            "tiers_evaluated": len(self._tier_results),
            "last_eval_log": self._eval_log[-3:] if self._eval_log else [],
        }


# ======================================================================
# TieredRouter — 扩展版，集成 6 层级路由 + 能力跟踪 + AgentFloor 评测
# ======================================================================

class TieredRouter:
    """层级路由：基于语义任务分析的路由到 6 个能力层级。

    在原有 4 层关键词匹配基础上升级到 6 层:
    - instruction_following, simple_tool, multi_tool, coordination, planning, long_horizon

    增加:
    - TaskClassifier: 语义任务分类
    - CapabilityTracker: 层级使用跟踪
    """

    TIERS = list(_TIER_ORDER)

    def __init__(self, enable_classifier: bool = True):
        self._routing_log: list[dict] = []
        self._total = 0
        self.enable_classifier = enable_classifier
        self.classifier = TaskClassifier() if enable_classifier else None
        self.tracker = CapabilityTracker()

    def route(self, task: str) -> dict:
        """路由任务到能力层级。

        当 enable_classifier=True 时，使用 TaskClassifier 的语义分析。
        否则使用原有的简化关键词匹配（基于 _TIER_KEYWORDS）。

        Args:
            task: 任务描述

        Returns:
            {"tier": str, "tier_index": int, "reason": str, ...}
        """
        self._total += 1

        if self.enable_classifier and self.classifier:
            result = self.classifier.classify(task)
            routing_result = {
                "tier": result["tier"],
                "tier_index": result["tier_index"],
                "reason": result["reason"],
                "confidence": result["confidence"],
                "scores": result["scores"],
                "features": result["features"],
            }
        else:
            # 原有 fallback
            low = task.lower()
            scores = {t: 0 for t in self.TIERS}
            tier_keywords = {
                "instruction_following": ["greet", "echo", "convert", "format", "simple math", "today", "time"],
                "simple_tool": ["search", "lookup", "calculate", "translate", "summarize", "find", "check"],
                "multi_tool": ["compare", "analyze", "aggregate", "combine", "cross"],
                "coordination": ["delegate", "coordinate", "orchestrate"],
                "planning": ["plan", "roadmap", "architecture", "design", "strategy"],
                "long_horizon": ["monitor", "track", "long-term", "ongoing", "continuous"],
            }
            for tier, keywords in tier_keywords.items():
                for kw in keywords:
                    if kw in low:
                        scores[tier] += 1

            selected = "instruction_following"
            for tier in reversed(self.TIERS):
                if scores[tier] > 0:
                    selected = tier
                    break

            routing_result = {
                "tier": selected,
                "tier_index": TIER_DEFINITIONS[selected]["index"],
                "reason": f"matched {scores[selected]} keywords",
                "confidence": 0.5,
            }

        self._routing_log.append(routing_result)

        # 记录到能力跟踪器 (默认标记为成功，调用者可在事后更新)
        self.tracker.record_outcome(
            routing_result["tier"],
            success=True,
            confidence=routing_result.get("confidence", 0.5),
        )

        return routing_result

    def record_failure(self, tier: str, reason: str) -> None:
        """记录一次失败的路由结果。"""
        self.tracker.record_outcome(tier, success=False, failure_reason=reason)

    def reset(self) -> None:
        """Reset router state: clear logs, reset tracker, retain config."""
        self._routing_log.clear()
        self._total = 0
        if self.classifier:
            self.classifier._classifications.clear()
        self.tracker.reset()

    def to_dict(self) -> dict:
        """Serialise router + classifier + tracker state to a dict."""
        return {
            "total": self._total,
            "routing_log": list(self._routing_log),
            "tracker": self.tracker.to_dict(),
            "classifier_classifications": (
                list(self.classifier._classifications)
                if self.classifier else []
            ),
        }

    @classmethod
    def from_dict(cls, data: dict, enable_classifier: bool = True) -> TieredRouter:
        """Restore router state from a dict produced by to_dict()."""
        router = cls(enable_classifier=enable_classifier)
        router._total = data.get("total", 0)
        router._routing_log = list(data.get("routing_log", []))
        if router.classifier:
            router.classifier._classifications = list(
                data.get("classifier_classifications", [])
            )
        router.tracker = CapabilityTracker.from_dict(data.get("tracker", {}))
        return router

    def get_stats(self) -> dict:
        distribution = {t: 0 for t in self.TIERS}
        for r in self._routing_log:
            t = r.get("tier", "unknown")
            distribution[t] = distribution.get(t, 0) + 1

        classifier_stats = {}
        if self.enable_classifier and self.classifier:
            classifier_stats = self.classifier.get_stats()

        return {
            "total": self._total,
            "distribution": distribution,
            "classifier": classifier_stats,
            "capability_tracker": {
                "overall": self.tracker.get_overall_stats(),
                "per_tier": self.tracker.get_tier_stats(),
            },
        }

    def get_capability_profile(self) -> dict:
        """获取能力概况 — 与 AgentFloor 评估输出格式兼容。"""
        tier_stats = self.tracker.get_tier_stats()
        profile = {
            "strongest_tier": None,
            "weakest_tier": None,
            "profile_summary": [],
        }
        best_rate = -1
        worst_rate = 2
        for t, s in tier_stats.items():
            rate = s["success_rate"]
            if rate > best_rate:
                best_rate = rate
                profile["strongest_tier"] = t
            if rate < worst_rate and s["attempts"] > 0:
                worst_rate = rate
                profile["weakest_tier"] = t
            profile["profile_summary"].append(
                f"{t}: {s['attempts']} attempts, {s['success_rate']*100:.0f}% success"
            )
        return profile
