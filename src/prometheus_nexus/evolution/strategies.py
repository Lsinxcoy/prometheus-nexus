"""MultiStrategyScheduler — Adaptive strategy selection with multiple bandit algorithms.

Based on: Legacy Omega strategies.py
Implements multiple exploration/exploitation strategies for adaptive selection:
    1. UCB1 — Upper Confidence Bound
    2. Thompson Sampling — Bayesian Bernoulli/Beta
    3. Epsilon-Greedy — with decay schedule
    4. Bayesian Optimization — GP-based acquisition

Key Concepts:
    1. Each strategy maintains its own state
    2. Meta-scheduler selects which strategy to use
    3. Strategies can be combined (ensemble)
    4. Automatic strategy switching based on regret bounds

Algorithm:
    for each round:
        meta_strategy = meta_scheduler.select()
        arm = meta_strategy.select(arms)
        reward = environment(arm)
        for s in all_strategies:
            s.update(arm, reward)
        meta_scheduler.update(all_strategies.performance)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class ArmInfo:
    """Information about a single arm/strategy option."""
    arm_id: str = ""
    pulls: int = 0
    total_reward: float = 0.0
    avg_reward: float = 0.0
    rewards: List[float] = field(default_factory=list)
    ucb_score: float = 0.0
    thompson_sample: float = 0.0
    last_pulled: float = 0.0


@dataclass
class StrategyResult:
    """Result from a strategy selection."""
    strategy_name: str = ""
    selected_arm: str = ""
    arm_score: float = 0.0
    all_scores: Dict[str, float] = field(default_factory=dict)
    timestamp: float = 0.0


class MultiStrategyScheduler:
    """Multi-strategy scheduler with UCB, Thompson, epsilon-greedy, and Bayesian.

    Based on legacy Omega strategies.py (~20KB).
    Implements multiple bandit algorithms with a meta-scheduler for
    adaptive strategy selection.

    Usage:
        scheduler = MultiStrategyScheduler(arm_ids=["A", "B", "C"])
        result = scheduler.select()
        scheduler.update(result.selected_arm, reward=0.8)
    """

    def __init__(self, arm_ids: List[str], epsilon: float = 0.1,
                 epsilon_decay: float = 0.995, epsilon_min: float = 0.01,
                 alpha_prior: float = 1.0, beta_prior: float = 1.0,
                 exploration_weight: float = 2.0):
        """Initialize multi-strategy scheduler.

        Args:
            arm_ids: List of arm/strategy identifiers.
            epsilon: Initial exploration rate for epsilon-greedy.
            epsilon_decay: Decay factor for epsilon.
            epsilon_min: Minimum epsilon value.
            alpha_prior: Alpha parameter for Thompson Beta prior.
            beta_prior: Beta parameter for Thompson Beta prior.
            exploration_weight: Weight for exploration in UCB1.
        """
        self._arm_ids = list(arm_ids)
        self._arms: Dict[str, ArmInfo] = {
            aid: ArmInfo(arm_id=aid) for aid in arm_ids
        }
        self._alpha = alpha_prior
        self._beta = beta_prior
        self._epsilon = epsilon
        self._epsilon_decay = epsilon_decay
        self._epsilon_min = epsilon_min
        self._exploration_weight = exploration_weight

        # Meta-scheduler state
        self._total_rounds = 0
        self._strategy_history: List[Dict[str, Any]] = []
        self._current_meta_strategy = "ucb1"  # ucb1, thompson, epsilon_greedy, bayesian, ensemble

        # Performance tracking for meta-scheduler
        self._strategy_performance: Dict[str, List[float]] = {
            "ucb1": [], "thompson": [], "epsilon_greedy": [],
            "bayesian": [], "ensemble": [],
        }

    def select(self, strategy: Optional[str] = None) -> StrategyResult:
        """Select an arm using the specified or meta-selected strategy.

        Args:
            strategy: Override strategy. None = use meta-scheduler.

        Returns:
            StrategyResult with selected arm and scores.
        """
        strat = strategy or self._current_meta_strategy

        if strat == "ucb1":
            selected, scores = self._ucb1_select()
        elif strat == "thompson":
            selected, scores = self._thompson_select()
        elif strat == "epsilon_greedy":
            selected, scores = self._epsilon_greedy_select()
        elif strat == "bayesian":
            selected, scores = self._bayesian_select()
        elif strat == "ensemble":
            selected, scores = self._ensemble_select()
        else:
            selected, scores = self._ucb1_select()

        result = StrategyResult(
            strategy_name=strat,
            selected_arm=selected,
            arm_score=scores.get(selected, 0.0),
            all_scores=scores,
            timestamp=time.time(),
        )

        self._total_rounds += 1
        self._strategy_history.append({
            "round": self._total_rounds,
            "strategy": strat,
            "arm": selected,
            "score": scores.get(selected, 0.0),
        })

        # Keep history bounded
        if len(self._strategy_history) > 10000:
            self._strategy_history = self._strategy_history[-5000:]

        return result

    def update(self, arm_id: str, reward: float, strategy: Optional[str] = None) -> None:
        """Update arm statistics with observed reward.

        Args:
            arm_id: The arm that was pulled.
            reward: The observed reward.
            strategy: Which strategy made this selection (for meta-learning).
        """
        if arm_id not in self._arms:
            self._arms[arm_id] = ArmInfo(arm_id=arm_id)

        arm = self._arms[arm_id]
        arm.pulls += 1
        arm.total_reward += reward
        arm.avg_reward = arm.total_reward / arm.pulls
        arm.rewards.append(reward)
        arm.last_pulled = time.time()

        # Keep rewards bounded
        if len(arm.rewards) > 1000:
            arm.rewards = arm.rewards[-500:]

        # Decay epsilon
        self._epsilon = max(self._epsilon_min, self._epsilon * self._epsilon_decay)

        # Track strategy performance for meta-scheduler
        strat = strategy or self._current_meta_strategy
        if strat in self._strategy_performance:
            self._strategy_performance[strat].append(reward)
            # Keep last 500 rewards for recency
            if len(self._strategy_performance[strat]) > 500:
                self._strategy_performance[strat] = self._strategy_performance[strat][-250:]

    def _ucb1_select(self) -> Tuple[str, Dict[str, float]]:
        """UCB1 selection: balance exploitation with exploration."""
        total_pulls = sum(a.pulls for a in self._arms.values())
        scores = {}

        for arm_id, arm in self._arms.items():
            if arm.pulls == 0:
                scores[arm_id] = float('inf')  # Prioritize unexplored arms
            else:
                exploitation = arm.avg_reward
                exploration = self._exploration_weight * math.sqrt(
                    math.log(total_pulls + 1) / arm.pulls
                )
                scores[arm_id] = exploitation + exploration
                arm.ucb_score = scores[arm_id]

        selected = max(scores, key=scores.get)
        return selected, scores

    def _thompson_select(self) -> Tuple[str, Dict[str, float]]:
        """Thompson Sampling with Beta-Bernoulli model.

        For each arm, maintain Beta(alpha, beta) posterior:
            alpha = 1 + sum(rewards > threshold)
            beta = 1 + sum(rewards <= threshold)
        Sample from each posterior, select highest.
        """
        scores = {}
        threshold = 0.5

        for arm_id, arm in self._arms.items():
            if arm.pulls == 0:
                scores[arm_id] = random.betavariate(self._alpha, self._beta)
            else:
                successes = sum(1 for r in arm.rewards if r >= threshold)
                failures = arm.pulls - successes
                alpha = self._alpha + successes
                beta_param = self._beta + failures
                scores[arm_id] = random.betavariate(alpha, beta_param)
                arm.thompson_sample = scores[arm_id]

        selected = max(scores, key=scores.get)
        return selected, scores

    def _epsilon_greedy_select(self) -> Tuple[str, Dict[str, float]]:
        """Epsilon-greedy: explore with probability epsilon, exploit otherwise."""
        # Exploration: random arm
        if random.random() < self._epsilon:
            selected = random.choice(self._arm_ids)
            scores = {aid: random.random() for aid in self._arm_ids}
            scores[selected] = max(scores.values())
            return selected, scores

        # Exploitation: best average reward
        scores = {}
        for arm_id, arm in self._arms.items():
            if arm.pulls == 0:
                scores[arm_id] = float('inf')
            else:
                scores[arm_id] = arm.avg_reward

        selected = max(scores, key=scores.get)
        return selected, scores

    def _bayesian_select(self) -> Tuple[str, Dict[str, float]]:
        """Bayesian optimization with GP-inspired acquisition function.

        Uses Expected Improvement (EI) approximation:
            EI(x) = (mu(x) - mu_best - xi) * Phi(Z) + sigma(x) * phi(Z)
        where Z = (mu(x) - mu_best - xi) / sigma(x)
        """
        mu_best = max((a.avg_reward for a in self._arms.values()), default=0.0)
        xi = 0.01  # Exploration parameter

        scores = {}
        for arm_id, arm in self._arms.items():
            if arm.pulls == 0:
                scores[arm_id] = 1.0  # High acquisition for unexplored
                continue

            mu = arm.avg_reward

            # Uncertainty estimate: std dev of rewards
            if len(arm.rewards) >= 2:
                variance = sum((r - mu) ** 2 for r in arm.rewards) / (len(arm.rewards) - 1)
                sigma = math.sqrt(variance) / math.sqrt(arm.pulls)
            else:
                sigma = 1.0 / math.sqrt(arm.pulls + 1)

            # Expected Improvement
            if sigma > 1e-10:
                z = (mu - mu_best - xi) / sigma
                ei = (mu - mu_best - xi) * self._norm_cdf(z) + sigma * self._norm_pdf(z)
            else:
                ei = max(0.0, mu - mu_best - xi)

            # Add uncertainty bonus for exploration
            scores[arm_id] = ei + 0.1 * sigma

        selected = max(scores, key=scores.get)
        return selected, scores

    def _ensemble_select(self) -> Tuple[str, Dict[str, float]]:
        """Ensemble: combine scores from all strategies, weighted voting."""
        # Get scores from each strategy
        ucb_arm, ucb_scores = self._ucb1_select()
        thompson_arm, thompson_scores = self._thompson_select()
        ei_arm, ei_scores = self._bayesian_select()

        # Normalize scores to [0, 1]
        def normalize(scores: Dict[str, float]) -> Dict[str, float]:
            if not scores:
                return scores
            vals = [v for v in scores.values() if not math.isinf(v)]
            if not vals:
                return scores
            mn, mx = min(vals), max(vals)
            if mx == mn:
                return {k: 0.5 for k in scores}
            return {k: (v - mn) / (mx - mn) if not math.isinf(v) else 1.0
                    for k, v in scores.items()}

        norm_ucb = normalize(ucb_scores)
        norm_thompson = normalize(thompson_scores)
        norm_ei = normalize(ei_scores)

        # Weighted combination
        weights = {"ucb1": 0.4, "thompson": 0.35, "bayesian": 0.25}
        combined = {}
        for arm_id in self._arm_ids:
            combined[arm_id] = (
                weights["ucb1"] * norm_ucb.get(arm_id, 0.0) +
                weights["thompson"] * norm_thompson.get(arm_id, 0.0) +
                weights["bayesian"] * norm_ei.get(arm_id, 0.0)
            )

        selected = max(combined, key=combined.get)
        return selected, combined

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Approximate standard normal CDF."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def _norm_pdf(x: float) -> float:
        """Standard normal PDF."""
        return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

    def update_meta_strategy(self) -> str:
        """Update meta-scheduler based on recent strategy performance.

        Switches to the strategy with best recent average reward.

        Returns:
            The selected meta-strategy name.
        """
        best_strat = self._current_meta_strategy
        best_avg = -1.0

        for strat, rewards in self._strategy_performance.items():
            if len(rewards) >= 5:
                avg = sum(rewards[-50:]) / min(len(rewards), 50)
                if avg > best_avg:
                    best_avg = avg
                    best_strat = strat

        self._current_meta_strategy = best_strat
        return best_strat

    def get_arm_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all arms."""
        result = {}
        for arm_id, arm in self._arms.items():
            recent_rewards = arm.rewards[-50:] if arm.rewards else []
            result[arm_id] = {
                "pulls": arm.pulls,
                "avg_reward": arm.avg_reward,
                "recent_avg": sum(recent_rewards) / len(recent_rewards) if recent_rewards else 0.0,
                "ucb_score": arm.ucb_score,
                "thompson_sample": arm.thompson_sample,
            }
        return result

    def get_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        strat_avgs = {}
        for strat, rewards in self._strategy_performance.items():
            if rewards:
                strat_avgs[strat] = sum(rewards[-50:]) / min(len(rewards), 50)

        return {
            "total_rounds": self._total_rounds,
            "current_strategy": self._current_meta_strategy,
            "epsilon": self._epsilon,
            "num_arms": len(self._arms),
            "strategy_avg_rewards": strat_avgs,
            "arm_stats": self.get_arm_stats(),
        }

    def reset_arm(self, arm_id: str) -> None:
        """Reset statistics for a single arm."""
        if arm_id in self._arms:
            self._arms[arm_id] = ArmInfo(arm_id=arm_id)

    def add_arm(self, arm_id: str) -> None:
        """Add a new arm to the scheduler."""
        if arm_id not in self._arms:
            self._arms[arm_id] = ArmInfo(arm_id=arm_id)
            self._arm_ids.append(arm_id)

    def remove_arm(self, arm_id: str) -> bool:
        """Remove an arm from the scheduler."""
        if arm_id in self._arms:
            del self._arms[arm_id]
            self._arm_ids.remove(arm_id)
            return True
        return False
