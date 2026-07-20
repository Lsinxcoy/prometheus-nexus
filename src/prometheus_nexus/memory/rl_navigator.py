"""RL Navigator — lightweight policy-gradient agent for HORMA hierarchy traversal.

Traverses a :class:`HierarchicalMemory` tree to select the minimal sufficient
context for a query.  Uses a simple linear policy:

    action = argmax(W · state)

Reward = task_success - token_penalty  (token_penalty ≈ number of nodes read).

Full-trajectory REINFORCE:
  - Collects (state, action, reward) tuples for the entire episode.
  - Uses discounted sum of rewards (return G_t) for each timestep.
  - Adds entropy bonus for exploration.
  - Log-probability gradient with baseline subtraction for variance reduction.

Reference: arXiv 2606.11680 — HORMA: Hierarchical Organization and Retrieval
via Multi-agent Architecture.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class RLNavigator:
    """Lightweight RL agent for traversing a HORMA hierarchy.

    The navigator starts at a query-derived prefix and walks down the tree,
    deciding at each level whether to drill deeper or stop and return the
    accumulated context.  The policy is a linear softmax over a small
    feature vector describing the current node and the query.

    Reward = task_success - token_penalty
        where token_penalty penalises reading many nodes (encourages minimal
        sufficient context).

    Uses **full-trajectory REINFORCE** with entropy bonus:

        1. Collect (state, action, reward) for each step of an episode.
        2. Compute discounted returns G_t = sum_{k>=t} gamma^{k-t} * r_k.
        3. Compute policy gradient: grad = sum_t G_t * grad(log pi(a_t|s_t))
        4. Add entropy bonus: H(pi) = -sum_a pi(a) * log(pi(a))

    Usage::

        from prometheus_nexus.memory.hierarchical_memory import HierarchicalMemory
        from prometheus_nexus.memory.rl_navigator import RLNavigator

        hm = HierarchicalMemory()
        hm.store("a1", "/tasks/explore", 0.9, content="alpha")
        hm.store("a2", "/tasks/explore/step1", 0.6, content="beta")

        nav = RLNavigator()
        context, actions = nav.navigate(hm, "/tasks/explore")
        nav.train(episodes=200)

        # Inspect learned policy
        policy = nav.get_policy_network()
    """

    def __init__(self, learning_rate: float = 0.01,
                 gamma: float = 0.99,
                 token_penalty: float = 0.05,
                 entropy_coef: float = 0.01) -> None:
        self._lock = threading.RLock()

        # Policy parameters (linear softmax: 2 actions: STOP=0, DRILL=1)
        # Features: [shared_depth_norm, utility, path_len_norm, bias]
        self._n_features = 4
        self._W: list[list[float]] = [
            [random.gauss(0, 0.1) for _ in range(self._n_features)]
            for _ in range(2)  # STOP, DRILL
        ]

        self._lr = learning_rate
        self._gamma = gamma
        self._token_penalty = token_penalty
        self._entropy_coef = entropy_coef

        # Training stats
        self._total_episodes = 0
        self._cumulative_reward = 0.0
        self._successes = 0
        self._total_tokens = 0

        # Baseline for variance reduction (moving average of returns)
        self._baseline = 0.0
        self._baseline_rate = 0.05

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def navigate(self, hierarchy: Any, query: str,
                 max_depth: int = 5) -> tuple[list[dict[str, Any]], list[int]]:
        """Traverse *hierarchy* to find minimal sufficient context for *query*.

        Args:
            hierarchy: A :class:`HierarchicalMemory` instance (duck-typed;
                must support ``retrieve(query, ...)`` and ``get_path(id)``).
            query: Path to navigate from.
            max_depth: Maximum drill depth before forced stop.

        Returns:
            ``(context_nodes, actions)`` — a list of retrieved node dicts and
            the sequence of actions taken (0=STOP, 1=DRILL).
        """
        with self._lock:
            actions: list[int] = []
            context: list[dict[str, Any]] = []
            current_path = query
            depth = 0

            while depth < max_depth:
                # Retrieve candidates at current path level.
                hits = hierarchy.retrieve(current_path, max_results=5)
                if not hits:
                    break

                # Build state vector for the current situation.
                state = self._build_state(hits, current_path, depth)
                # Sample action from policy.
                action = self._sample_action(state)
                actions.append(action)

                if action == 0:  # STOP
                    context.extend(hits)
                    break
                else:  # DRILL
                    context.extend(hits)
                    # Move to the most promising child path.
                    next_path = self._select_child_path(hits, current_path)
                    if next_path == current_path:
                        # No deeper path available.
                        break
                    current_path = next_path
                    depth += 1

            # If we exhausted max_depth, include whatever we have.
            if depth >= max_depth:
                more = hierarchy.retrieve(current_path, max_results=5)
                context.extend(m for m in more if m not in context)

        return context, actions

    def train(self, episodes: int = 100,
              eval_hierarchy: Any = None,
              eval_queries: list[str] | None = None) -> dict[str, float]:
        """Train the navigator via full-trajectory REINFORCE with entropy bonus.

        For each episode:
          1. Collect (state, action, reward) tuples for all step.
          2. Compute discounted returns G_t = sum_{k>=t} gamma^{k-t} * r_k.
          3. Compute policy gradient with baseline subtraction.
          4. Add entropy regularisation.
          5. Update policy weights.

        Args:
            episodes: Number of training episodes.
            eval_hierarchy: Optional hierarchy for eval (same as train if None).
            eval_queries: Queries to evaluate after training.

        Returns:
            Summary dict with reward, success rate, and average tokens.
        """
        # Create a training hierarchy if none provided.
        if eval_hierarchy is None:
            from prometheus_nexus.memory.hierarchical_memory import \
                HierarchicalMemory
            hm = HierarchicalMemory()
            self._populate_training_data(hm)
        else:
            hm = eval_hierarchy

        if eval_queries is None:
            queries = [
                "/tasks/explore",
                "/tasks/explore/step1",
                "/science/biology",
            ]
        else:
            queries = eval_queries

        episode_rewards: list[float] = []

        for ep in range(episodes):
            query = random.choice(queries)

            # --- Full-trajectory collection ---
            trajectory: list[tuple[list[float], int, float]] = []

            # Run navigation step-by-step, collecting (state, action) pairs
            # with step-wise rewards.
            with self._lock:
                context: list[dict[str, Any]] = []
                actions: list[int] = []
                states: list[list[float]] = []
                current_path = query
                depth = 0

                while depth < 4:  # max_depth = 4 during training
                    hits = hm.retrieve(current_path, max_results=5)
                    if not hits:
                        break

                    state = self._build_state(hits, current_path, depth)
                    action = self._sample_action(state)

                    states.append(state)
                    actions.append(action)

                    if action == 0:  # STOP
                        context.extend(hits)
                        break
                    else:  # DRILL
                        context.extend(hits)
                        next_path = self._select_child_path(hits, current_path)
                        if next_path == current_path:
                            break
                        current_path = next_path
                        depth += 1

                if depth >= 4:
                    more = hm.retrieve(current_path, max_results=5)
                    context.extend(m for m in more if m not in context)

            # Compute reward for the trajectory
            task_success = 1.0 if len(context) >= 1 else 0.0
            token_cost = len(context) * self._token_penalty
            reward = task_success - token_cost

            # Build trajectory with per-step rewards
            # (intermediate rewards: 0 for drill steps, final reward for the episode)
            n_steps = len(actions)
            step_rewards = [0.0] * n_steps
            if actions:
                # The last action gets the full reward; intermediate steps get 0
                step_rewards[-1] = reward

            trajectory = list(zip(states, actions, step_rewards))

            # --- Full-trajectory REINFORCE update ---
            self._full_trajectory_update(trajectory)

            episode_rewards.append(reward)

            with self._lock:
                self._total_episodes += 1
                self._cumulative_reward += reward
                if task_success > 0.5:
                    self._successes += 1
                self._total_tokens += len(context)

        # Summary
        with self._lock:
            avg_reward = (self._cumulative_reward /
                          max(self._total_episodes, 1))
            success_rate = (self._successes /
                            max(self._total_episodes, 1))
            avg_tokens = (self._total_tokens /
                          max(self._total_episodes, 1))

        return {
            "avg_reward": round(avg_reward, 4),
            "success_rate": round(success_rate, 4),
            "avg_tokens": round(avg_tokens, 2),
            "episodes": self._total_episodes,
        }

    def get_policy_network(self) -> dict[str, Any]:
        """Return the current policy weights for analysis.

        Returns:
            Dict with:
            - "weights": list of [action_index][feature_index] weights
            - "n_features": number of features
            - "n_actions": number of actions
            - "feature_labels": human-readable feature names
        """
        with self._lock:
            return {
                "weights": [list(row) for row in self._W],
                "n_features": self._n_features,
                "n_actions": 2,
                "feature_labels": [
                    "shared_depth_norm",
                    "avg_utility",
                    "path_len_norm",
                    "bias",
                ],
                "action_labels": ["STOP (0)", "DRILL (1)"],
            }

    def get_stats(self) -> dict[str, Any]:
        """Return navigator training statistics."""
        with self._lock:
            total = max(self._total_episodes, 1)
            return {
                "total_episodes": self._total_episodes,
                "cumulative_reward": round(self._cumulative_reward, 4),
                "avg_reward": round(self._cumulative_reward / total, 4),
                "success_rate": round(self._successes / total, 4),
                "avg_tokens": round(self._total_tokens / total, 2),
                "learning_rate": self._lr,
                "gamma": self._gamma,
                "token_penalty": self._token_penalty,
                "entropy_coef": self._entropy_coef,
                "baseline": round(self._baseline, 4),
            }

    # ------------------------------------------------------------------
    # Full-trajectory REINFORCE
    # ------------------------------------------------------------------

    def _full_trajectory_update(
        self,
        trajectory: list[tuple[list[float], int, float]],
    ) -> None:
        """Full-trajectory REINFORCE with entropy bonus and baseline.

        For each timestep *t* in the trajectory:

            1. Compute discounted return:
                   G_t = sum_{k=t}^{T-1} gamma^{k-t} * r_k

            2. Compute advantage: A_t = G_t - baseline

            3. Policy gradient:
                   grad = A_t * grad(log pi(a_t|s_t))

            4. Entropy bonus:
                   H(pi(s_t)) = -sum_a pi(a|s_t) * log(pi(a|s_t))
                   entropy_grad = entropy_coef * grad(H)

            5. Weight update:
                   W[a][i] += lr * (grad + entropy_grad)

            6. Update baseline (moving average).

        Args:
            trajectory: List of (state, action, reward) tuples.
        """
        if not trajectory:
            return

        T = len(trajectory)

        # --- Step 1: Compute discounted returns ---
        returns = [0.0] * T
        running_return = 0.0
        for t in reversed(range(T)):
            _, _, reward = trajectory[t]
            running_return = reward + self._gamma * running_return
            returns[t] = running_return

        with self._lock:
            lr = self._lr
            gamma = self._gamma
            ec = self._entropy_coef

            # --- Step 2-5: Accumulate gradients over the trajectory ---
            grad_accum: list[list[float]] = [
                [0.0] * self._n_features for _ in range(2)
            ]

            for t, (state, action, _) in enumerate(trajectory):
                G_t = returns[t]

                # Advantage with baseline subtraction (variance reduction)
                advantage = G_t - self._baseline

                # Compute action probabilities for this state
                logits = [
                    sum(w * s for w, s in zip(weights, state))
                    for weights in self._W
                ]
                max_logit = max(logits)
                exp_logits = [math.exp(l - max_logit) for l in logits]
                total = sum(exp_logits)
                probs = [e / total for e in exp_logits]

                # Log-probability of taken action (for REINFORCE gradient)
                log_prob = math.log(max(probs[action], 1e-15))

                # Policy gradient: grad = A_t * grad(log pi(a|s))
                #   grad(log pi(a|s)) for linear softmax = state * (1 - p)
                for i in range(self._n_features):
                    grad_accum[action][i] += advantage * state[i] * (1.0 - probs[action])

                # --- Entropy bonus ---
                # H(pi) = -sum_a pi(a) * log(pi(a))
                entropy = -sum(
                    p * math.log(max(p, 1e-15)) for p in probs
                )
                # Grad of entropy w.r.t. W[a][i]:
                #   dH/dW[a][i] = pi(a|s) * state[i] * (log(pi(a|s)) + 1 - sum_b pi(b) * log(pi(b)))
                # Simplified: dH/dW[a][i] = -probs[a] * state[i] * (log_prob + 1)
                for act_idx in range(2):
                    for i in range(self._n_features):
                        grad_accum[act_idx][i] += (
                            ec * probs[act_idx] * state[i] *
                            (math.log(max(probs[act_idx], 1e-15)) + 1.0)
                        )

            # Apply accumulated gradient (averaged over trajectory length)
            for act_idx in range(2):
                for i in range(self._n_features):
                    self._W[act_idx][i] += lr * grad_accum[act_idx][i] / T

            # Update baseline (moving average of returns)
            # Use the first return as representative
            if returns:
                self._baseline = (
                    (1.0 - self._baseline_rate) * self._baseline +
                    self._baseline_rate * returns[0]
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_state(self, hits: list[dict[str, Any]],
                     current_path: str, depth: int) -> list[float]:
        """Build a 4-dimensional feature vector.

        Features:
            0. normalised shared depth (0..1)
            1. average utility of hits
            2. normalised path length
            3. bias (always 1.0)
        """
        shared_depth = len(current_path.strip("/").split("/")) if current_path != "/" else 0
        max_depth = 10.0
        depth_norm = min(shared_depth / max_depth, 1.0)

        avg_utility = (
            sum(h.get("score", 0.0) for h in hits) / max(len(hits), 1)
        )

        path_len = len(current_path) / 100.0  # normalise

        return [depth_norm, avg_utility, path_len, 1.0]

    def _sample_action(self, state: list[float]) -> int:
        """Sample an action from the softmax policy."""
        logits = [
            sum(w * s for w, s in zip(weights, state))
            for weights in self._W
        ]
        # Softmax.
        max_logit = max(logits)
        exp_logits = [math.exp(l - max_logit) for l in logits]
        total = sum(exp_logits)
        probs = [e / total for e in exp_logits]

        # Stochastic sample.
        r = random.random()
        cumulative = 0.0
        for action, p in enumerate(probs):
            cumulative += p
            if r < cumulative:
                return action
        return 0  # fallback

    def _select_child_path(self, hits: list[dict[str, Any]],
                           current_path: str) -> str:
        """Pick the deepest unique path among *hits* as the next drill target."""
        best = current_path
        max_depth = len(current_path.strip("/").split("/")) if current_path != "/" else 0
        for h in hits:
            p = h.get("path", "")
            if p.startswith(current_path) and p != current_path:
                pd = len(p.strip("/").split("/"))
                if pd > max_depth:
                    max_depth = pd
                    best = p
        return best

    @staticmethod
    def _populate_training_data(hm: Any) -> None:
        """Fill a hierarchy with sample nodes for training."""
        samples = [
            ("node_1", "/tasks/explore", 0.9, "exploration task"),
            ("node_2", "/tasks/explore/step1", 0.6, "step 1 details"),
            ("node_3", "/tasks/explore/step2", 0.7, "step 2 details"),
            ("node_4", "/science/biology", 0.8, "biology overview"),
            ("node_5", "/science/biology/cell", 0.5, "cell biology"),
            ("node_6", "/science/physics", 0.7, "physics overview"),
            ("node_7", "/tasks/eval", 0.4, "evaluation task"),
        ]
        for nid, path, utility, content in samples:
            hm.store(nid, path, utility, content)
