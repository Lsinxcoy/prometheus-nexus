"""ReflexionEngine — Self-reflection with verbal reinforcement learning.

Based on: "Reflexion: Language Agents with Verbal Reinforcement Learning"
(arXiv:2303.11366, Shinn et al. 2023)

Key Concepts from Paper:
    1. Verbal reflection is more efficient than weight updates
    2. Self-reflection → episodic memory → retrieval for next attempt
    3. Reflection generates natural language critique of failures
    4. Each attempt: actor → evaluator → reflexion → next attempt

Paper Finding:
    "Reflexion improves HumanEval pass@1 from 80% to 91% (+11%)
     and improves HotPotQA F1 from 15% to 24% (+9%)"

Algorithm:
    for each attempt:
        action = actor(context, reflection_memory)
        reward = evaluator(action)
        if reward < threshold:
            reflection = self_reflect(action, reward, context)
            reflection_memory.append(reflection)

Complexity: O(A × R) where A = attempts, R = reflection depth
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class ReflexionReflection:
    """A verbal reflection on an attempt."""
    attempt: int = 0
    action: str = ""
    reward: float = 0.0
    critique: str = ""
    improvement_suggestion: str = ""
    timestamp: float = 0.0


@dataclass
class AttemptRecord:
    """Record of a single attempt."""
    attempt: int = 0
    action: str = ""
    reward: float = 0.0
    reflection: ReflexionReflection | None = None
    timestamp: float = 0.0


class ReflexionEngine:
    """Self-reflection with verbal reinforcement learning.

    Based on Reflexion paper (arXiv:2303.11366).

    Usage:
        engine = ReflexionEngine(max_attempts=5)
        for i in range(5):
            action = f"attempt_{i}"
            reward = evaluate(action)
            engine.record_attempt(action, reward)
            if reward >= 0.8:
                break
            engine.reflect(action, reward)
    """

    def __init__(self, max_attempts: int = 10, reflection_threshold: float = 0.7,
                 max_reflections: int = 100):
        """Initialize the reflexion engine.

        Args:
            max_attempts: Maximum number of attempts.
            reflection_threshold: Reward threshold below which reflection triggers.
            max_reflections: Maximum reflections to store.
        """
        self._max_attempts = max_attempts
        self._reflection_threshold = reflection_threshold
        self._max_reflections = max_reflections

        self._attempts: list[AttemptRecord] = []
        self._reflections: list[ReflexionReflection] = []
        self._reflection_memory: list[str] = []
        self._failure_patterns: Counter = Counter()
        self._success_patterns: Counter = Counter()

    def record_attempt(self, action: str, reward: float) -> AttemptRecord:
        """Record an attempt and its reward.

        Args:
            action: The action taken.
            reward: Reward signal [0, 1].

        Returns:
            AttemptRecord with reflection if reward < threshold.
        """
        attempt = len(self._attempts) + 1
        record = AttemptRecord(attempt=attempt, action=action, reward=reward, timestamp=time.time())

        if reward < self._reflection_threshold:
            reflection = self.reflect(action, reward)
            record.reflection = reflection

        self._attempts.append(record)
        return record

    def reflect(self, action: str, reward, context: str = "") -> Reflection:
        """Generate a verbal reflection on a failed attempt.

        Args:
            action: The action that was taken.
            reward: The reward received (float or string).
            context: Additional context about the attempt.

        Returns:
            Reflection with critique and improvement suggestion.
        """
        # Convert reward to float if string
        if isinstance(reward, str):
            try:
                reward = float(reward.split("=")[-1].split("}")[0])
            except (ValueError, IndexError):
                reward = 0.5
        # Generate critique based on reward level
        if reward < 0.2:
            critique = f"Action '{action[:50]}' failed completely (reward={reward:.2f}). " \
                      f"The approach was fundamentally wrong."
            suggestion = "Try a completely different strategy."
        elif reward < 0.5:
            critique = f"Action '{action[:50]}' partially failed (reward={reward:.2f}). " \
                      f"Some aspects worked but key parts were wrong."
            suggestion = "Keep the working parts, modify the failing parts."
        else:
            critique = f"Action '{action[:50]}' was close but not sufficient (reward={reward:.2f})."
            suggestion = "Fine-tune the approach, focus on the gap."

        # Track patterns
        keywords = set(action.lower().split()) & {"error", "fail", "timeout", "wrong", "missing"}
        for kw in keywords:
            self._failure_patterns[f"{kw}"] += 1

        reflection = ReflexionReflection(
            attempt=len(self._attempts) + 1,
            action=action, reward=reward,
            critique=critique,
            improvement_suggestion=suggestion,
            timestamp=time.time(),
        )

        self._reflections.append(reflection)
        self._reflection_memory.append(f"Attempt {reflection.attempt}: {critique} → {suggestion}")

        if len(self._reflections) > self._max_reflections:
            self._reflections = self._reflections[-self._max_reflections // 2:]
            self._reflection_memory = self._reflection_memory[-self._max_reflections // 2:]

        return reflection

    def get_reflection_context(self, top_k: int = 3, query: str = "") -> str:
        """Get relevant reflections as context for the next attempt.

        From paper: "retrieval of relevant past reflections improves subsequent attempts"
        If query provided, retrieves by keyword relevance; otherwise by recency.
        """
        if query and self._reflections:
            query_words = set(query.lower().split())
            scored = []
            for r in self._reflections:
                reflection_words = set(r.action.lower().split())
                relevance = len(query_words & reflection_words)
                scored.append((relevance, r))
            scored.sort(key=lambda x: -x[0])
            relevant = [r for _, r in scored[:top_k] if scored[0][0] > 0]
            if relevant:
                return "Relevant reflections:\n" + "\n".join(
                    f"- {r.critique} → {r.improvement_suggestion}" for r in relevant
                )

        recent = self._reflection_memory[-top_k:]
        if not recent:
            return ""
        return "Previous reflections:\n" + "\n".join(f"- {r}" for r in recent)

    def get_worst_actions(self, top_k: int = 5) -> list[dict]:
        """Get the worst-performing actions."""
        action_scores: dict[str, list[float]] = {}
        for a in self._attempts:
            action_scores.setdefault(a.action, []).append(a.reward)
        ranked = [(a, sum(s) / len(s)) for a, s in action_scores.items() if s]
        ranked.sort(key=lambda x: x[1])
        return [{"action": a, "avg_reward": r} for a, r in ranked[:top_k]]

    def get_improvement_trend(self) -> list[float]:
        """Get the reward trend across attempts."""
        return [a.reward for a in self._attempts]

    def get_stats(self) -> dict:
        rewards = [a.reward for a in self._attempts]
        return {
            "attempts": len(self._attempts),
            "reflections": len(self._reflections),
            "avg_reward": sum(rewards) / max(len(rewards), 1),
            "best_reward": max(rewards) if rewards else 0,
            "failure_patterns": len(self._failure_patterns),
            "improvement_suggestions": len(self._reflection_memory),
        }
