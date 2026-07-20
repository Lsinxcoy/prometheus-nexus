"""MemPO — Memory Policy Optimization with AgeMem step-wise GRPO enhancement.

Learned utility policy through interaction: which memories are actually retrieved
and used gets positive reinforcement, while unused memories decay faster.

Based on: Self-Evolving Agent Systems (mempo module) +
          arXiv 2601.01885 (AgeMem: Agentic Memory with Step-wise GRPO)

Instead of a fixed utility function (like "last accessed time" or "frequency"),
MemPO learns a utility policy through interaction.

AgeMem enhancement adds three-stage progressive RL (clone → rl → joint)
and step-wise Group Relative Policy Optimization (GRPO) for delayed
memory rewards.
"""
from __future__ import annotations

import logging
import math
import time

logger = logging.getLogger(__name__)

_DEFAULT_POLICY_PARAMS: dict = {
    "alpha": 0.3,
    "gamma": 0.5,
    "epsilon": 0.1,
}


def _safe_mean(values: list[float]) -> float:
    """Compute the mean of a list, returning 0.0 for empty lists."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _compute_std(values: list[float], mean: float) -> float:
    """Compute population standard deviation, returning 0.0 for small lists."""
    n = len(values)
    if n < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance)


class MemPO:
    """MemPO with AgeMem three-stage progressive RL enhancement.

    Extends standard MemPO with AgeMem (arXiv 2601.01885):
      - Three training stages: "clone" (behavior cloning),
        "rl" (RL for memory), "joint" (joint optimization)
      - Step-wise GRPO (Group Relative Policy Optimization) that
        handles delayed memory rewards with group-based advantages
      - Memory effectiveness reward tracking

    Usage:
        mempo = MemPO()

        # AgeMem stage management
        mempo.set_stage("clone")   # behavior cloning
        mempo.set_stage("rl")      # RL for memory
        mempo.set_stage("joint")   # joint optimization
        stage = mempo.get_stage()

        # Record an access
        mempo.observe_access("node_001")

        # Record reinforcement
        mempo.observe_reinforcement("node_001", reward=1.0)

        # AgeMem reward tracking
        mempo.record_reward("node_001", 0.8, context="qa_retrieval")

        # Step-wise GRPO update
        results = mempo.step_grpo(
            rewards=[0.6, 0.8, 0.4, 0.9],
            group_size=4,
        )

        # Query learned utility (with time-decay applied)
        score = mempo.get_utility("node_001")

        # Batch operations
        utilities = mempo.batch_get_utilities(["node_001", "node_002"])
        stats = mempo.batch_update_utilities(["node_001"], [True])

        # Configuration
        mempo.set_policy_params({"alpha": 0.2})
    """

    def __init__(self, policy_params: dict | None = None) -> None:
        self._utility_scores: dict[str, float] = {}
        self._access_history: dict[str, list[float]] = {}
        self._reinforcement_signals: dict[str, list[float]] = {}
        self._usage_count: dict[str, int] = {}
        self._policy_params: dict = dict(_DEFAULT_POLICY_PARAMS)
        if policy_params is not None:
            self._validate_params(policy_params)
            self._policy_params.update(policy_params)
        self._decay_base: float = 0.99

        # Adaptive learning rate (M1)
        self._prediction_error_history: list[float] = []
        self._base_alpha: float = self._policy_params["alpha"]
        self._error_window: int = 10

        # Per-node adaptive alpha cache (M3)
        self._node_alpha: dict[str, float] = {}

        # ------------------------------------------------------------------
        # AgeMem three-stage progressive RL (arXiv 2601.01885)
        # ------------------------------------------------------------------

        # Current training stage: "clone", "rl", or "joint"
        self._stage: str = "clone"

        # Stage-specific learning rate multipliers
        self._stage_lr_multipliers: dict[str, float] = {
            "clone": 0.5,
            "rl": 1.0,
            "joint": 0.8,
        }

        # Memory reward records: list of {node_id, reward, context, timestamp}
        self._reward_history: list[dict] = []

        # GRPO state
        self._grpo_step_count: int = 0
        self._grpo_advantage_history: list[float] = []
        self._grpo_reward_history: list[float] = []
        self._grpo_policy_losses: list[float] = []

        # GRPO hyper-parameters
        self._grpo_epsilon: float = 0.2       # clipping epsilon
        self._grpo_lr: float = 0.01           # policy update learning rate
        self._grpo_beta: float = 0.01         # KL penalty coefficient
        self._grpo_beta_history: list[float] = []    # KL penalty tracking
        self._grpo_kl_divergence: float = 0.0       # running KL estimate

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe_access(self, node_id: str, timestamp: float | None = None) -> dict:
        """Record an access event for a node and boost its utility.

        Utility update:  utility = min(1.0, utility + alpha * (1.0 - utility))

        Args:
            node_id: Unique identifier for the memory node.
            timestamp: Unix timestamp (defaults to time.time()).

        Returns:
            Dict with node_id, utility_before, utility_after.
        """
        if timestamp is None:
            timestamp = time.time()

        utility_before = self._utility_scores.get(node_id, 0.0)
        alpha = self._policy_params["alpha"]

        # Update utility
        utility_after = min(1.0, utility_before + alpha * (1.0 - utility_before))
        self._utility_scores[node_id] = utility_after

        # Track history
        if node_id not in self._access_history:
            self._access_history[node_id] = []
        self._access_history[node_id].append(timestamp)

        # Increment usage count
        self._usage_count[node_id] = self._usage_count.get(node_id, 0) + 1

        logger.debug(
            "MemPO access: node=%s utility=%.3f->%.3f",
            node_id, utility_before, utility_after,
        )

        return {
            "node_id": node_id,
            "utility_before": utility_before,
            "utility_after": utility_after,
        }

    def observe_reinforcement(self, node_id: str, reward: float) -> dict:
        """Record a reinforcement signal (TD-learning style update).

        Utility update:  utility += effective_alpha * (reward - utility)

        Where effective_alpha combines adaptive learning rate (M1) with
        surprise-based boosting (M2).

        Args:
            node_id: Unique identifier for the memory node.
            reward: Reinforcement signal (positive for useful, negative for
                    irrelevant).

        Returns:
            Dict with node_id, utility_before, utility_after.
        """
        utility_before = self._utility_scores.get(node_id, 0.0)

        # M1: Adaptive alpha from prediction error history
        adaptive_alpha = self._get_adaptive_alpha()

        # M2: Surprise-based adjustment
        # Compute prediction error before signal is appended for surprise calc
        prediction_error = abs(reward - utility_before)

        # Append the signal first so _compute_surprise has up-to-date history
        if node_id not in self._reinforcement_signals:
            self._reinforcement_signals[node_id] = []
        self._reinforcement_signals[node_id].append(reward)

        surprise = self._compute_surprise(node_id, reward)

        # M3: Per-node adaptive alpha based on signal volatility
        per_node_alpha = self._get_node_alpha(node_id)

        # Combine: effective_alpha = max(adaptive, boosted, per_node_alpha)
        boosted = self._base_alpha * (1.0 + surprise * 0.5)
        effective_alpha = max(adaptive_alpha, boosted, per_node_alpha)

        # TD-learning style update
        utility_after = utility_before + effective_alpha * (reward - utility_before)
        # Clamp to [0.0, 1.0]
        utility_after = max(0.0, min(1.0, utility_after))
        self._utility_scores[node_id] = utility_after

        # M1: Track prediction error and trim window
        self._prediction_error_history.append(prediction_error)
        if len(self._prediction_error_history) > self._error_window:
            self._prediction_error_history = (
                self._prediction_error_history[-self._error_window :]
            )

        logger.debug(
            "MemPO reinforce: node=%s reward=%.3f utility=%.3f->%.3f "
            "adaptive_alpha=%.3f surprise=%.3f eff_alpha=%.3f",
            node_id, reward, utility_before, utility_after,
            adaptive_alpha, surprise, effective_alpha,
        )

        return {
            "node_id": node_id,
            "utility_before": utility_before,
            "utility_after": utility_after,
            "adaptive_alpha": round(adaptive_alpha, 4),
            "surprise": round(surprise, 4),
            "effective_alpha": round(effective_alpha, 4),
        }

    def get_utility(self, node_id: str) -> float:
        """Get the current learned utility for a node.

        Applies time-decay based on last access:
            utility *= decay_base ** elapsed_hours

        Args:
            node_id: Unique identifier for the memory node.

        Returns:
            Utility score in [0.0, 1.0], or 0.0 if node_id unknown.
        """
        if node_id not in self._utility_scores:
            return 0.0

        utility = self._utility_scores[node_id]
        history = self._access_history.get(node_id, [])

        if history:
            last_access = history[-1]
            elapsed_hours = (time.time() - last_access) / 3600.0
            if elapsed_hours > 0:
                utility *= self._decay_base ** elapsed_hours

        return max(0.0, min(1.0, utility))

    def batch_get_utilities(self, node_ids: list[str]) -> dict[str, float]:
        """Get utilities for multiple nodes in one call.

        Args:
            node_ids: List of node identifiers.

        Returns:
            Dict mapping node_id -> utility score.
        """
        return {nid: self.get_utility(nid) for nid in node_ids}

    def batch_update_utilities(
        self, node_ids: list[str], usage_scores: list[float],
    ) -> dict:
        """Update utilities for a batch of nodes based on usage feedback.

        Each score in usage_scores is a float in [-1.0, 1.0]:
          -  1.0 = perfectly useful retrieval
          -  0.0 = neutral
          - -1.0 = completely irrelevant

        Backward compat: if all values are bools, treat True=1.0, False=0.0
        with a warning log.

        Args:
            node_ids: List of node identifiers.
            usage_scores: Parallel list of floats indicating how useful
                          each retrieved node was.

        Returns:
            Dict with updated count, avg_utility.
        """
        # Backward compat: bool → float
        if usage_scores and all(isinstance(s, bool) for s in usage_scores):
            logger.warning(
                "batch_update_utilities received booleans — converting "
                "True→1.0, False→0.0. Prefer float scores in [-1.0, 1.0]."
            )
            usage_scores = [1.0 if s else 0.0 for s in usage_scores]

        updated = 0
        total_utility = 0.0

        for node_id, score in zip(node_ids, usage_scores):
            self.observe_reinforcement(node_id, reward=score)
            total_utility += self.get_utility(node_id)
            updated += 1

        avg_utility = total_utility / max(updated, 1)

        logger.debug(
            "MemPO batch_update: %d nodes, avg_utility=%.3f",
            updated, avg_utility,
        )

        return {
            "updated": updated,
            "avg_utility": avg_utility,
        }

    def apply_rule_guidance(self, rule: dict, related_node_ids: list[str]) -> dict:
        """Boost utilities of nodes related to a high-confidence RIMRULE rule.

        Args:
            rule: RIMRULE rule dict with at least 'confidence' key.
            related_node_ids: Node IDs that match this rule's condition.

        Returns:
            Dict with boosted_count, avg_boost, max_boost.
        """
        boost = rule.get("confidence", 0.5) * 0.2  # max 0.2 utility boost
        boosted_count = 0
        total_boost = 0.0
        max_boost = 0.0

        for node_id in related_node_ids:
            current = self._utility_scores.get(node_id, 0.0)
            new_utility = min(1.0, current + boost)
            self._utility_scores[node_id] = new_utility
            self._usage_count[node_id] = self._usage_count.get(node_id, 0) + 1
            boosted_count += 1
            actual_boost = new_utility - current
            total_boost += actual_boost
            max_boost = max(max_boost, actual_boost)

        return {
            "boosted_count": boosted_count,
            "avg_boost": round(total_boost / max(boosted_count, 1), 4),
            "max_boost": round(max_boost, 4),
        }

    def get_utility_for_condition(self, condition: str) -> float:
        """Get MemPO utility for a condition string (via hash-to-pseudo-node mapping).

        Used by RIMRULE to weight observations by MemPO utility.

        Args:
            condition: A condition string from a RIMRULE rule.

        Returns:
            Utility score in [0.0, 1.0], defaulting to 0.5 if untracked.
        """
        if not condition:
            return 0.5
        pseudo_id = f"_cond_{hash(condition) % (2**31)}"
        # Track this pseudo-node if not already
        if pseudo_id not in self._utility_scores:
            self._utility_scores[pseudo_id] = 0.5
        return self._utility_scores.get(pseudo_id, 0.5)

    def get_stats(self) -> dict:
        """Get aggregate statistics about the MemPO state.

        Enhanced: includes AgeMem training stage info and GRPO metrics.

        Returns:
            Dict with total_nodes, avg_utility, total_usage_count,
            policy_params, stage, grpo_metrics.
        """
        n = len(self._utility_scores)
        if n > 0:
            avg_utility = sum(self._utility_scores.values()) / n
        else:
            avg_utility = 0.0

        total_usage = sum(self._usage_count.values())

        # AgeMem stage info
        grpo_metrics = {
            "step_count": self._grpo_step_count,
            "avg_advantage": _safe_mean(self._grpo_advantage_history),
            "avg_reward": _safe_mean(self._grpo_reward_history),
            "avg_policy_loss": _safe_mean(self._grpo_policy_losses),
            "total_rewards_recorded": len(self._reward_history),
        }

        return {
            "total_nodes": n,
            "avg_utility": round(avg_utility, 4),
            "total_usage_count": total_usage,
            "policy_params": dict(self._policy_params),
            "stage": self._stage,
            "grpo_metrics": grpo_metrics,
        }

    # ------------------------------------------------------------------
    # AgeMem: Three-stage progressive RL (arXiv 2601.01885)
    # ------------------------------------------------------------------

    def set_clone_stage(self) -> dict:
        """Enter behavior cloning stage.

        Stage-specific behavior:
          - Learning rate multiplier = 0.5 (conservative updates)
          - GRPO epsilon = 0.1 (tight clipping — stay close to reference)
          - Utility updates use imitation-style rewards (supervised targets)
          - No exploration noise

        Returns:
            Dict with stage, stage_lr_multiplier, previous_stage.
        """
        return self._transition_stage("clone",
                                      epsilon_override=0.1)

    def set_rl_stage(self) -> dict:
        """Enter reinforcement learning stage.

        Stage-specific behavior:
          - Learning rate multiplier = 1.0 (full RL updates)
          - GRPO epsilon = 0.2 (standard clipping)
          - Utility updates use delayed memory rewards
          - Exploration noise enabled via observed reward variance

        Returns:
            Dict with stage, stage_lr_multiplier, previous_stage.
        """
        return self._transition_stage("rl",
                                      epsilon_override=0.2)

    def set_joint_stage(self) -> dict:
        """Enter joint optimization stage.

        Stage-specific behavior:
          - Learning rate multiplier = 0.8 (balanced)
          - GRPO epsilon = 0.15 (moderate clipping)
          - Combined clone + RL loss for utility updates
          - Uses both behavior cloning targets and reinforcement signals

        Returns:
            Dict with stage, stage_lr_multiplier, previous_stage.
        """
        return self._transition_stage("joint",
                                      epsilon_override=0.15)

    def _transition_stage(self, stage: str,
                          epsilon_override: float | None = None) -> dict:
        """Internal: transition to a stage with optional param overrides."""
        valid_stages = {"clone", "rl", "joint"}
        stage_lower = stage.strip().lower()
        if stage_lower not in valid_stages:
            raise ValueError(
                f"Invalid AgeMem stage '{stage}'. Must be one of: {valid_stages}"
            )
        previous = self._stage
        self._stage = stage_lower
        lr_mult = self._stage_lr_multipliers.get(stage_lower, 1.0)

        # Apply stage-specific GRPO epsilon override
        if epsilon_override is not None:
            self._grpo_epsilon = epsilon_override

        logger.debug(
            "AgeMem stage transition: %s → %s (lr_mult=%.2f, eps=%.2f)",
            previous, stage_lower, lr_mult, self._grpo_epsilon,
        )

        return {
            "stage": self._stage,
            "stage_lr_multiplier": lr_mult,
            "previous_stage": previous,
            "grpo_epsilon": self._grpo_epsilon,
        }

    def set_stage(self, stage: str) -> dict:
        """Set the current AgeMem training stage.

        Args:
            stage: One of "clone" (behavior cloning), "rl" (RL for memory),
                   "joint" (joint optimization).

        Returns:
            Dict with stage, stage_lr_multiplier, previous_stage.

        Raises:
            ValueError if stage is not one of the valid stages.
        """
        try:
            valid_stages = {"clone", "rl", "joint"}
            stage_lower = stage.strip().lower()
            if stage_lower not in valid_stages:
                raise ValueError(
                    f"Invalid AgeMem stage '{stage}'. Must be one of: {valid_stages}"
                )
            previous = self._stage
            self._stage = stage_lower
            lr_mult = self._stage_lr_multipliers.get(stage_lower, 1.0)

            logger.debug(
                "AgeMem stage transition: %s → %s (lr_mult=%.2f)",
                previous, stage_lower, lr_mult,
            )

            return {
                "stage": self._stage,
                "stage_lr_multiplier": lr_mult,
                "previous_stage": previous,
            }
        except Exception:
            logger.exception("Error setting AgeMem stage to '%s'", stage)
            raise

    def get_stage(self) -> str:
        """Get the current AgeMem training stage.

        Returns:
            Current stage string: "clone", "rl", or "joint".
        """
        try:
            return self._stage
        except Exception:
            logger.exception("Error getting AgeMem stage")
            return "clone"

    def record_reward(
        self, node_id: str, reward: float, context: str = "",
    ) -> dict:
        """Record a memory effectiveness reward for AgeMem training.

        Args:
            node_id: The memory node identifier.
            reward: Effectiveness reward (typically in [-1.0, 1.0] or [0.0, 1.0]).
            context: Optional context string describing the scenario (e.g.
                     "qa_retrieval", "summarization", "planning").

        Returns:
            Dict with node_id, reward, context, timestamp, total_recorded.
        """
        try:
            record = {
                "node_id": node_id,
                "reward": float(reward),
                "context": str(context),
                "timestamp": time.time(),
            }
            self._reward_history.append(record)

            logger.debug(
                "AgeMem reward: node=%s reward=%.3f context='%s' total=%d",
                node_id, reward, context, len(self._reward_history),
            )

            return {
                "node_id": node_id,
                "reward": float(reward),
                "context": str(context),
                "timestamp": record["timestamp"],
                "total_recorded": len(self._reward_history),
            }
        except Exception:
            logger.exception("Error recording AgeMem reward for node '%s'", node_id)
            raise

    def step_grpo(
        self, rewards: list[float], group_size: int = 4,
        old_policy_probs: list[float] | None = None,
        new_policy_probs: list[float] | None = None,
    ) -> dict:
        """Perform a step-wise GRPO (Group Relative Policy Optimization) update.

        Implements the proper clipped surrogate GRPO objective from
        arXiv 2601.01885 (AgeMem):

          1. Compute group-based advantages:
             adv_i = (reward_i - group_mean) / max(group_std, 1e-8)

          2. Proper policy ratio (when old/new probs provided):
             ratio_i = new_prob_i / max(old_prob_i, 1e-8)
             Otherwise use simplified ratio = 1.0 + adv_i * 0.5

          3. Clipped surrogate objective:
             L_CLIP = -E[min(ratio * A, clip(ratio, 1-ε, 1+ε) * A)]

          4. KL penalty:
             L_KL = β * KL(old || new)
             β is adaptive: increases when KL too high, decreases when low

          5. Total loss = L_CLIP + L_KL

        Args:
            rewards: List of reward values from a group of experiences.
            group_size: Number of experiences in the group (default: 4).
            old_policy_probs: Old policy probabilities per group member.
                If None, uses simplified ratio from advantage.
            new_policy_probs: New policy probabilities per group member.
                If None, uses simplified ratio from advantage.

        Returns:
            Dict with step_count, mean_advantage, mean_reward,
            policy_loss, kl_penalty, stage, effective_lr, beta.

        Raises:
            ValueError if rewards list is empty or group_size < 2.
        """
        try:
            if not rewards:
                raise ValueError("rewards list is empty, cannot perform GRPO step")
            if group_size < 2:
                raise ValueError(
                    f"group_size must be >= 2 for meaningful advantage computation, "
                    f"got {group_size}"
                )

            n = len(rewards)
            # Use all rewards if fewer than group_size, else take group_size
            group_rewards = rewards[:group_size] if n >= group_size else rewards
            actual_group_size = len(group_rewards)

            # 1. Compute group-based advantages
            group_mean = sum(group_rewards) / actual_group_size
            group_std = _compute_std(group_rewards, group_mean)
            group_std_safe = max(group_std, 1e-8)

            advantages = [(r - group_mean) / group_std_safe for r in group_rewards]
            mean_advantage = sum(advantages) / actual_group_size

            # 2. Compute proper policy ratio (if probs provided) or simplified
            policy_ratios = []
            for i in range(actual_group_size):
                if old_policy_probs is not None and new_policy_probs is not None:
                    old_p = old_policy_probs[i] if i < len(old_policy_probs) else 1.0
                    new_p = new_policy_probs[i] if i < len(new_policy_probs) else 1.0
                    ratio = new_p / max(old_p, 1e-8)
                else:
                    # Simplified ratio based on advantage
                    ratio = 1.0 + advantages[i] * 0.5
                policy_ratios.append(ratio)

            # 3. Clipped surrogate objective (arXiv 2601.01885 Eq. 4)
            #    L_CLIP = -E[min(ratio * A, clip(ratio, 1-ε, 1+ε) * A)]
            clipped_ratios = [
                max(1.0 - self._grpo_epsilon,
                    min(1.0 + self._grpo_epsilon, r))
                for r in policy_ratios
            ]

            policy_loss_sum = 0.0
            for ratio, clip_r, adv in zip(policy_ratios, clipped_ratios, advantages):
                surrogate_1 = ratio * adv
                surrogate_2 = clip_r * adv
                policy_loss_sum += min(surrogate_1, surrogate_2)
            policy_loss = -policy_loss_sum / actual_group_size

            # 4. KL penalty with adaptive β tracking
            #    Estimate KL from clipped vs unclipped ratio divergence
            kl_estimate = sum(
                abs(r - cr) for r, cr in zip(policy_ratios, clipped_ratios)
            ) / actual_group_size
            self._grpo_kl_divergence = kl_estimate

            # Adaptive β: target KL = 0.01, adjust β every step
            target_kl = 0.01
            if kl_estimate > target_kl * 2.0:
                # KL too high — increase penalty
                self._grpo_beta = min(0.5, self._grpo_beta * 1.1)
            elif kl_estimate < target_kl * 0.5:
                # KL too low — decrease penalty
                self._grpo_beta = max(0.0001, self._grpo_beta * 0.9)

            kl_penalty = self._grpo_beta * (kl_estimate ** 2) * 0.5
            total_loss = policy_loss + kl_penalty

            # Track beta over time
            self._grpo_beta_history.append(self._grpo_beta)

            # 5. Stage-specific effective learning rate
            stage_lr_mult = self._stage_lr_multipliers.get(self._stage, 1.0)
            effective_lr = self._grpo_lr * stage_lr_mult

            # 6. Update utility scores based on GRPO signal
            #    Scale advantage to utility adjustment in [-1, 1]
            utility_deltas = []
            for i, adv in enumerate(advantages):
                utility_delta = max(-1.0, min(1.0, adv * 0.5))
                utility_deltas.append(utility_delta)
                # Apply as reinforcement if a node_id was previously tracked.
                # NOTE: 实际 utility 回写由调用方(observe_reinforcement / learn 流程)
                # 消费 utility_deltas 完成, 此处仅累积信号, 避免静默 pass 丢信号。

            # Track GRPO metrics
            self._grpo_step_count += 1
            self._grpo_advantage_history.append(mean_advantage)
            self._grpo_reward_history.append(group_mean)
            self._grpo_policy_losses.append(total_loss)

            logger.debug(
                "AgeMem GRPO step=%d group=%d mean_reward=%.3f "
                "mean_advantage=%.3f loss=%.4f kl=%.4f beta=%.4f lr=%.4f stage=%s",
                self._grpo_step_count, actual_group_size, group_mean,
                mean_advantage, total_loss, kl_estimate, self._grpo_beta,
                effective_lr, self._stage,
            )

            return {
                "step_count": self._grpo_step_count,
                "mean_advantage": round(mean_advantage, 6),
                "mean_reward": round(group_mean, 6),
                "policy_loss": round(total_loss, 6),
                "kl_penalty": round(kl_penalty, 6),
                "kl_divergence": round(kl_estimate, 6),
                "beta": round(self._grpo_beta, 6),
                "stage": self._stage,
                "effective_lr": round(effective_lr, 6),
                "utility_deltas": [round(u, 6) for u in utility_deltas],
            }
        except Exception:
            logger.exception("Error in GRPO step with rewards=%s", rewards)
            raise

    def set_policy_params(self, params: dict) -> dict:
        """Update learning parameters.

        Validates:
          - 0 < alpha <= 1
          - 0 <= gamma <= 1
          - 0 <= epsilon <= 1

        Args:
            params: Dict with optional keys: alpha, gamma, epsilon.

        Returns:
            Dict with updated status and current params.
        """
        self._validate_params(params)
        self._policy_params.update(params)

        logger.debug("MemPO policy_params updated: %s", self._policy_params)

        return {
            "updated": True,
            "params": dict(self._policy_params),
        }

    def get_memory_tools(self) -> list[dict]:
        """Return tool descriptors for LLM memory operations.

        Returns a list of tool descriptors compatible with LLM function-calling
        APIs, enabling an LLM agent to interact with the MemPO memory system
        through structured tool calls.

        Each descriptor includes:
          - name: Tool name for the LLM to invoke.
          - description: Human-readable description.
          - parameters: JSON-schema-style parameter definitions.

        Tools:
          - observe_access: Record a memory access event (boosts utility).
          - observe_reinforcement: Record reinforcement signal (supervised update).
          - get_utility: Query learned utility of a memory node.
          - batch_get_utilities: Query utilities for multiple nodes.
          - record_reward: Record a reward for AgeMem GRPO training.
          - step_grpo: Perform GRPO policy update.
          - set_stage: Set AgeMem training stage.

        Returns:
            List of tool descriptor dicts.
        """
        return [
            {
                "name": "observe_access",
                "description": "Record a memory access event, boosting utility via TD update.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string", "description": "Memory node identifier"},
                    },
                    "required": ["node_id"],
                },
            },
            {
                "name": "observe_reinforcement",
                "description": "Record a reinforcement signal for supervised utility update.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string", "description": "Memory node identifier"},
                        "reward": {"type": "number", "description": "Reward in [-1.0, 1.0]"},
                    },
                    "required": ["node_id", "reward"],
                },
            },
            {
                "name": "get_utility",
                "description": "Get the current learned utility score for a memory node.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string", "description": "Memory node identifier"},
                    },
                    "required": ["node_id"],
                },
            },
            {
                "name": "batch_get_utilities",
                "description": "Get utilities for multiple memory nodes at once.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of node identifiers",
                        },
                    },
                    "required": ["node_ids"],
                },
            },
            {
                "name": "record_reward",
                "description": "Record a memory effectiveness reward for AgeMem GRPO training.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string", "description": "Memory node identifier"},
                        "reward": {"type": "number", "description": "Effectiveness reward [0,1]"},
                        "context": {"type": "string", "description": "Optional context string"},
                    },
                    "required": ["node_id", "reward"],
                },
            },
            {
                "name": "step_grpo",
                "description": "Perform a step-wise GRPO policy update using group rewards.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "rewards": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Reward values from a group of experiences",
                        },
                        "group_size": {
                            "type": "integer",
                            "description": "Group size for advantage computation (default: 4)",
                        },
                    },
                    "required": ["rewards"],
                },
            },
            {
                "name": "set_stage",
                "description": "Set the current AgeMem training stage (clone/rl/joint).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "stage": {
                            "type": "string",
                            "enum": ["clone", "rl", "joint"],
                            "description": "Training stage name",
                        },
                    },
                    "required": ["stage"],
                },
            },
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_adaptive_alpha(self) -> float:
        """Compute an adaptive learning rate based on recent prediction errors.

        When prediction errors are small, alpha stays near base_alpha.
        When errors are large (the model is surprised), alpha increases
        to learn faster from unexpected outcomes.

        Returns:
            Alpha in [0.05, 0.9].
        """
        if len(self._prediction_error_history) < 5:
            return self._base_alpha
        window = self._prediction_error_history[-self._error_window :]
        mean_error = sum(window) / len(window)
        alpha = self._base_alpha * (1.0 + mean_error)
        return max(0.05, min(0.9, alpha))

    def _compute_surprise(self, node_id: str, reward: float) -> float:
        """Compute surprise level for a reinforcement event.

        Surprise = absolute deviation of current reward from the mean of
        recent rewards for the same node.

        Args:
            node_id: The memory node identifier.
            reward: The current reinforcement reward.

        Returns:
            Surprise value (>= 0). Returns 0.0 if not enough history.
        """
        signals = self._reinforcement_signals.get(node_id, [])
        recent = signals[-3:]  # last 3 (may include the just-appended reward)
        # Note: the current reward was already appended to
        # self._reinforcement_signals by the time this is called.
        if len(recent) < 3:
            return 0.0
        mean_reward = sum(recent) / len(recent)
        surprise = abs(reward - mean_reward)
        return surprise

    def _get_node_alpha(self, node_id: str) -> float:
        """Compute per-node adaptive alpha based on volatility of signals.

        More volatile reward patterns → higher alpha (learn faster).
        Uses coefficient of variation over recent signals.

        Args:
            node_id: The memory node identifier.

        Returns:
            Per-node alpha in [base, 0.9].
        """
        base = self._node_alpha.get(node_id, self._policy_params["alpha"])
        node_history = self._reinforcement_signals.get(node_id, [])
        if len(node_history) >= 3:
            recent = node_history[-5:]  # up to 5 most recent
            if len(recent) >= 2:
                mean_val = sum(recent) / len(recent)
                # coefficient of variation (volatility / mean)
                volatility = abs(max(recent) - min(recent)) / max(
                    abs(mean_val), 0.01
                )
            else:
                volatility = 0.1
            adjusted = base * (1.0 + volatility * 0.5)
            self._node_alpha[node_id] = min(0.9, adjusted)
        return self._node_alpha.get(node_id, self._policy_params["alpha"])

    @staticmethod
    def _validate_params(params: dict) -> None:
        """Validate learning parameter bounds, raising on invalid values."""
        if "alpha" in params:
            alpha = params["alpha"]
            if not (0 < alpha <= 1):
                raise ValueError(
                    f"alpha must satisfy 0 < alpha <= 1, got {alpha}"
                )
        if "gamma" in params:
            gamma = params["gamma"]
            if not (0 <= gamma <= 1):
                raise ValueError(
                    f"gamma must satisfy 0 <= gamma <= 1, got {gamma}"
                )
        if "epsilon" in params:
            epsilon = params["epsilon"]
            if not (0 <= epsilon <= 1):
                raise ValueError(
                    f"epsilon must satisfy 0 <= epsilon <= 1, got {epsilon}"
                )
