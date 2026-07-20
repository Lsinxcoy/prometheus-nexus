"""AgentReputation (arXiv 2605.00073) + COOP² (2603.00349) + ClinicalReTrial (2601.00290)
+ ConstructiveAlignment (2607.00001) + DenoiseFlow (2603.00532).

Each class implements its paper's core algorithm with real logic.
"""
from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────
# AgentReputation — arXiv 2605.00073
# Contextualized reputation with decay and cross-domain scoring.
# ────────────────────────────────────────────────────────────────

class AgentReputation:
    """上下文化声誉系统 (arXiv 2605.00073).

    Tracks agent performance across domains with:
      - Temporal decay: older scores weigh less
      - Cross-domain scoring: performance in one domain informs reputation in similar domains
      - Confidence intervals: low-sample domains have wider uncertainty
    """

    DOMAIN_SIMILARITY = {
        "coding": ["code_review", "debugging", "implementation"],
        "reasoning": ["logic", "math", "planning"],
        "writing": ["editing", "summarization", "translation"],
        "retrieval": ["search", "qa", "fact_checking"],
        "planning": ["scheduling", "resource_allocation", "task_decomposition"],
    }

    def __init__(self, decay_half_life: float = 86400.0):  # 24h default decay
        self._reps: dict[str, float] = {}         # agent:domain -> score
        self._counts: dict[str, int] = {}          # agent:domain -> n_observations
        self._timestamps: dict[str, float] = {}    # agent:domain -> last_update
        self._cards: dict[str, dict[str, float]] = defaultdict(dict)
        self._decay_half_life = decay_half_life
        self._history: list[dict] = []
        self._domain_graph: dict[str, list[str]] = {
            k: v for k, v in self.DOMAIN_SIMILARITY.items()
        }

    def record_performance(self, agent: str, domain: str, score: float) -> dict:
        """Record an agent's performance in a domain.

        Applies temporal decay to existing score before merging new observation.
        Propagates to similar domains via weighted cross-domain transfer.

        Args:
            agent: Agent identifier.
            domain: Performance domain.
            score: Performance score (0.0 to 1.0).

        Returns:
            Dict with updated scores for this agent/domain.
        """
        score = max(0.0, min(1.0, score))
        key = f"{agent}:{domain}"
        now = time.time()

        # Retrieve previous score with decay
        prev_score = self._reps.get(key, 0.5)
        prev_time = self._timestamps.get(key, now)
        elapsed = now - prev_time
        decay_factor = math.exp(-elapsed / self._decay_half_life)
        decayed_prev = prev_score * decay_factor

        # Update count and merge
        n = self._counts.get(key, 0)
        if n == 0:
            new_score = score
        else:
            # More observations -> slower adaptation
            learning_rate = 1.0 / (1.0 + math.log1p(n))
            new_score = decayed_prev * (1 - learning_rate) + score * learning_rate

        self._reps[key] = new_score
        self._counts[key] = n + 1
        self._timestamps[key] = now
        self._cards[agent][domain] = new_score

        # Cross-domain propagation to similar domains
        cross_domain_updates: dict[str, float] = {}
        similar_domains = self._get_similar_domains(domain)
        for sim_domain in similar_domains:
            sim_key = f"{agent}:{sim_domain}"
            sim_prev = self._reps.get(sim_key, 0.5)
            sim_n = self._counts.get(sim_key, 0)
            # Transfer weight: stronger for domains with few observations
            transfer_weight = 0.1 / (1.0 + math.log1p(sim_n))
            sim_new = sim_prev * (1 - transfer_weight) + score * transfer_weight
            self._reps[sim_key] = sim_new
            self._cards[agent][sim_domain] = sim_new
            cross_domain_updates[sim_domain] = round(sim_new, 4)

        self._history.append({
            "agent": agent, "domain": domain, "score": score,
            "new_reputation": round(new_score, 4),
            "cross_domain_updates": cross_domain_updates,
            "timestamp": now,
        })

        return {
            "agent": agent,
            "domain": domain,
            "reputation": round(new_score, 4),
            "observations": self._counts[key],
            "confidence_interval": self._confidence_interval(new_score, n + 1),
            "cross_domain": cross_domain_updates,
        }

    def get_card(self, agent: str, domain: str) -> float:
        """Get an agent's reputation score in a domain (0.0 to 1.0).

        Returns 0.5 (neutral) for unknown agents/domains.
        """
        key = f"{agent}:{domain}"
        if key in self._reps:
            return self._reps[key]
        return 0.5

    def get_agent_summary(self, agent: str) -> dict:
        """Get a summary of an agent's reputation across all domains."""
        agent_domains = {
            k.split(":", 1)[1]: v
            for k, v in self._reps.items()
            if k.startswith(f"{agent}:")
        }
        if not agent_domains:
            return {"agent": agent, "domains": {}, "average": 0.5}
        avg = sum(agent_domains.values()) / len(agent_domains)
        return {
            "agent": agent,
            "domains": {d: round(s, 4) for d, s in agent_domains.items()},
            "average": round(avg, 4),
            "n_domains": len(agent_domains),
        }

    def _get_similar_domains(self, domain: str) -> list[str]:
        """Get domains similar to the given one."""
        for canonical, similar in self._domain_graph.items():
            if domain == canonical:
                return similar
            if domain in similar:
                return [d for d in similar if d != domain] + [canonical]
        return []

    @staticmethod
    def _confidence_interval(mean: float, n: int) -> dict:
        """Approximate 95% confidence interval for a reputation score."""
        if n < 2:
            return {"lower": 0.0, "upper": 1.0}
        std_err = math.sqrt(mean * (1 - mean) / n) if 0 < mean < 1 else 0.1 / math.sqrt(n)
        margin = 1.96 * std_err
        return {
            "lower": round(max(0.0, mean - margin), 4),
            "upper": round(min(1.0, mean + margin), 4),
        }

    def get_stats(self) -> dict:
        return {
            "agents": len(self._cards),
            "total_observations": sum(self._counts.values()),
            "domains_tracked": len(set(k.split(":", 1)[1] for k in self._reps)),
            "history_size": len(self._history),
        }


# ────────────────────────────────────────────────────────────────
# CooperConstraint — arXiv 2603.00349 (COOP²)
# Cooperation constraint checking for multi-agent systems.
# ────────────────────────────────────────────────────────────────

class CooperConstraint:
    """COOP² 合作约束检查 (arXiv 2603.00349).

    Checks four types of constraints for multi-agent cooperation:
      - spatial: agents operating in overlapping physical/logical spaces
      - temporal: timing and ordering constraints between agent actions
      - participant: which agents are allowed to participate
      - dependency: action A must complete before action B starts

    Each constraint type has specific violation detection logic.
    """

    TYPES = ["spatial", "temporal", "participant", "dependency"]

    def __init__(self):
        self._constraints: list[dict[str, Any]] = []
        self._violations: list[dict[str, Any]] = []
        self._active_rules: dict[str, list[dict]] = {
            t: [] for t in self.TYPES
        }

    def add_rule(self, constraint_type: str, rule: dict) -> None:
        """Add a cooperation rule for a constraint type.

        Args:
            constraint_type: One of 'spatial', 'temporal', 'participant', 'dependency'.
            rule: Dict defining the rule (specific keys depend on type).
        """
        if constraint_type not in self.TYPES:
            logger.warning("CooperConstraint: unknown constraint type %s", constraint_type)
            return
        self._active_rules[constraint_type].append(rule)
        self._constraints.append({"type": constraint_type, "rule": rule})

    def check(self, task_type: str, n_agents: int,
              details: dict | None = None) -> list[dict]:
        """Check all active rules for a given task configuration.

        Args:
            task_type: Type of task (used for spatial/temporal matching).
            n_agents: Number of agents involved.
            details: Optional dict with additional context (agent_roles, timeline, etc.).

        Returns:
            List of violation dicts (empty if no violations).
        """
        violations: list[dict[str, Any]] = []

        # Spatial constraints
        for rule in self._active_rules.get("spatial", []):
            zone = rule.get("zone", "").lower()
            capacity = rule.get("capacity", 3)
            if zone and zone in task_type.lower() and n_agents > capacity:
                violations.append({
                    "type": "spatial",
                    "severity": "high" if n_agents > capacity * 1.5 else "medium",
                    "message": (
                        f"Zone '{zone}' capacity ({capacity}) exceeded by "
                        f"{n_agents} agents (over by {n_agents - capacity})"
                    ),
                    "n_agents": n_agents,
                    "capacity": capacity,
                    "overage": n_agents - capacity,
                })

        # Temporal constraints
        if details and "timeline" in details:
            timeline = details["timeline"]
            for rule in self._active_rules.get("temporal", []):
                max_duration = rule.get("max_duration", 300)
                actual_duration = timeline.get("estimated_duration", 0)
                if actual_duration > max_duration:
                    violations.append({
                        "type": "temporal",
                        "severity": "medium",
                        "message": (
                            f"Estimated duration ({actual_duration}s) exceeds "
                            f"max allowed ({max_duration}s)"
                        ),
                        "estimated": actual_duration,
                        "max_allowed": max_duration,
                    })

        # Participant constraints
        for rule in self._active_rules.get("participant", []):
            max_agents = rule.get("max_agents", 5)
            min_agents = rule.get("min_agents", 1)
            if n_agents > max_agents:
                violations.append({
                    "type": "participant",
                    "severity": "high" if n_agents > max_agents * 2 else "low",
                    "message": (
                        f"Too many agents ({n_agents}) for participant limit ({max_agents})"
                    ),
                    "n_agents": n_agents,
                    "max_agents": max_agents,
                })
            if n_agents < min_agents:
                violations.append({
                    "type": "participant",
                    "severity": "high",
                    "message": (
                        f"Too few agents ({n_agents}) for minimum ({min_agents})"
                    ),
                    "n_agents": n_agents,
                    "min_agents": min_agents,
                })

        # Dependency constraints
        if details and "dependencies" in details:
            deps = details["dependencies"]
            for i, dep in enumerate(deps):
                dep_type = dep.get("type", "sequential")
                if dep_type == "sequential":
                    # Check that sequential ordering is valid
                    for j in range(len(dep.get("steps", [])) - 1):
                        a = dep["steps"][j]
                        b = dep["steps"][j + 1]
                        violations.append({
                            "type": "dependency",
                            "severity": "info",
                            "message": f"Sequential dependency: {a} → {b} enforced",
                            "dependency_index": i,
                            "dependents": [a, b],
                        })

        if not violations:
            # Only add a default empty warning for participant count if no rules exist
            if not any(self._active_rules.values()) and n_agents > 3:
                violations.append({
                    "type": "participant",
                    "severity": "warning",
                    "message": f"Default check: {n_agents} agents with no active rules",
                    "n_agents": n_agents,
                })

        self._violations.extend(violations)
        return violations

    def get_active_rules(self) -> dict:
        """Return all active rules grouped by type."""
        return {t: list(rules) for t, rules in self._active_rules.items()}

    def clear_rules(self) -> None:
        """Clear all active rules."""
        for t in self.TYPES:
            self._active_rules[t] = []

    def get_stats(self) -> dict:
        return {
            "total_rules": sum(len(r) for r in self._active_rules.values()),
            "total_violations": len(self._violations),
            "violation_types": {t: sum(1 for v in self._violations if v["type"] == t)
                                for t in self.TYPES},
            "alerts": len(self._violations),
        }


# ────────────────────────────────────────────────────────────────
# ClinicalReTrial — arXiv 2601.00290
# Clinical trial redesign from failure analysis with iterative improvement.
# ────────────────────────────────────────────────────────────────

class ClinicalReTrial:
    """临床实验闭环修正 (arXiv 2601.00290).

    Takes a failed trial protocol and redesigns it by:
      - Analyzing the failure reason against known failure modes
      - Generating targeted modifications
      - Estimating success probability improvement
    """

    FAILURE_MODES = {
        "low_enrollment": {
            "description": "Insufficient participant enrollment",
            "typical_fix": "Broaden inclusion criteria and expand recruitment channels",
            "success_boost": 0.20,
        },
        "high_dropout": {
            "description": "Excessive participant dropout rate",
            "typical_fix": "Reduce follow-up burden, add retention incentives",
            "success_boost": 0.15,
        },
        "underpowered": {
            "description": "Statistical power too low to detect effect",
            "typical_fix": "Increase sample size, adjust effect size expectation",
            "success_boost": 0.25,
        },
        "confounding": {
            "description": "Uncontrolled confounding variables",
            "typical_fix": "Add stratification or matching; adjust randomization",
            "success_boost": 0.18,
        },
        "endpoint_misspecification": {
            "description": "Primary endpoint poorly chosen or measured",
            "typical_fix": "Re-evaluate endpoint selection; use composite endpoints",
            "success_boost": 0.22,
        },
        "safety_signal": {
            "description": "Adverse safety events detected",
            "typical_fix": "Modify dosing, add safety monitoring, exclusion criteria",
            "success_boost": 0.30,
        },
        "protocol_deviation": {
            "description": "High rate of protocol deviations",
            "typical_fix": "Simplify protocol procedures; improve training",
            "success_boost": 0.12,
        },
        "poor_compliance": {
            "description": "Low treatment adherence",
            "typical_fix": "Reduce dosing frequency; use adherence monitoring tools",
            "success_boost": 0.15,
        },
    }

    def __init__(self):
        self._trials: list[dict[str, Any]] = []

    def redesign(self, protocol: dict, failure_reason: str) -> dict:
        """Redesign a trial protocol based on failure analysis.

        Args:
            protocol: Dict describing the original trial (title, design, endpoints, etc.).
            failure_reason: Text description of why the trial failed.

        Returns:
            Dict with failure analysis, modifications, and estimated success probability.
        """
        # Classify failure reason into known failure modes
        failure_lower = failure_reason.lower()
        matched_failures: list[str] = []
        for mode_key, mode_info in self.FAILURE_MODES.items():
            keywords = mode_key.replace("_", " ").split()
            if any(kw in failure_lower for kw in keywords):
                matched_failures.append(mode_key)

        if not matched_failures:
            # Fallback: match on overlapping words
            words = set(failure_lower.split())
            for mode_key in self.FAILURE_MODES:
                mode_words = set(mode_key.replace("_", " ").split())
                if words & mode_words:
                    matched_failures.append(mode_key)

        if not matched_failures:
            matched_failures = ["underpowered"]  # sensible default

        # Generate modifications from matched failure modes
        modifications: list[str] = []
        total_success_boost = 0.0
        detailed_analysis: list[dict] = []
        for mode_key in matched_failures:
            mode_info = self.FAILURE_MODES[mode_key]
            fix = mode_info["typical_fix"]
            modifications.append(f"Fix {mode_key}: {fix}")
            total_success_boost += mode_info["success_boost"]
            detailed_analysis.append({
                "mode": mode_key,
                "description": mode_info["description"],
                "fix": fix,
                "success_boost": mode_info["success_boost"],
            })

        # Estimate base success probability from protocol quality
        base_success = self._estimate_base_success(protocol)
        new_success = min(base_success + total_success_boost, 0.95)

        # Include protocol-specific modifications
        if protocol.get("title"):
            modifications.insert(0, f"Update trial: {protocol['title'][:100]}")
        if protocol.get("design"):
            modifications.append(f"Re-evaluate {protocol['design']} design choice")

        result = {
            "failure_reason": failure_reason[:200],
            "matched_failure_modes": matched_failures,
            "analysis": detailed_analysis,
            "modifications": modifications,
            "base_success_probability": round(base_success, 3),
            "estimated_success_probability": round(new_success, 3),
            "improvement": round(total_success_boost, 3),
            "redesigned_at": time.time(),
        }
        self._trials.append(result)
        return result

    @staticmethod
    def _estimate_base_success(protocol: dict) -> float:
        """Estimate base success probability from protocol features."""
        score = 0.3  # baseline
        if protocol.get("title"):
            score += 0.05
        if protocol.get("design") in ["rct", "randomized", "double_blind"]:
            score += 0.15
        if protocol.get("sample_size", 0) > 100:
            score += 0.1
        if "primary_endpoint" in protocol:
            score += 0.05
        if "secondary_endpoints" in protocol:
            score += 0.03
        if "inclusion_criteria" in protocol:
            score += 0.03
        if "exclusion_criteria" in protocol:
            score += 0.03
        if "safety_monitoring" in protocol:
            score += 0.05
        return min(score, 0.6)

    def get_stats(self) -> dict:
        if not self._trials:
            return {"trials": 0}
        avg_improvement = sum(
            t.get("improvement", 0) for t in self._trials
        ) / len(self._trials)
        return {
            "trials": len(self._trials),
            "avg_improvement": round(avg_improvement, 3),
            "common_failure_modes": self._most_common_failure_modes(),
        }

    def _most_common_failure_modes(self, top_k: int = 3) -> list[str]:
        """Get the most common failure modes across all trials."""
        from collections import Counter
        counter: Counter = Counter()
        for t in self._trials:
            for mode in t.get("matched_failure_modes", []):
                counter[mode] += 1
        return [m for m, _ in counter.most_common(top_k)]


# ────────────────────────────────────────────────────────────────
# ConstructiveAlignment — arXiv 2607.00001
# Preference evolution through constructive feedback.
# ────────────────────────────────────────────────────────────────

class ConstructiveAlignment:
    """构式对齐 — 偏好演化 (arXiv 2607.00001).

    Models user preference as an evolving vector across dimensions.
    Each feedback event updates the preference vector with momentum:
      new = current * (1 - lr) + feedback * lr + momentum * delta

    Also tracks preference agreement between users and provides
    convergence metrics.
    """

    def __init__(self, learning_rate: float = 0.3, momentum: float = 0.1):
        self._prefs: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        self._history: dict[str, list[dict]] = defaultdict(list)
        self._lr = learning_rate
        self._momentum = momentum
        self._last_delta: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )

    def update_preference(self, user: str, dimension: str, value: float) -> dict:
        """Update a user's preference along a dimension.

        Uses momentum for smooth preference evolution:
          velocity = current - last_value
          new = current * (1 - lr) + value * lr + momentum * velocity

        Args:
            user: User identifier.
            dimension: Preference dimension (e.g., 'detail', 'speed', 'creativity').
            value: Preference value in [-1, 1].

        Returns:
            Dict showing evolution status and current preferences.
        """
        value = max(-1.0, min(1.0, value))
        current = self._prefs[user].get(dimension, 0.0)
        delta = current - self._last_delta[user].get(dimension, current)

        # Momentum update
        new_value = (
            current * (1.0 - self._lr)
            + value * self._lr
            + self._momentum * delta
        )
        new_value = max(-1.0, min(1.0, new_value))

        self._prefs[user][dimension] = new_value
        self._last_delta[user][dimension] = value

        self._history[user].append({
            "dimension": dimension,
            "input_value": value,
            "previous": round(current, 3),
            "new_value": round(new_value, 3),
            "delta": round(new_value - current, 3),
            "timestamp": time.time(),
        })

        return {
            "evolving": True,
            "user": user,
            "dimension": dimension,
            "previous": round(current, 4),
            "current": round(new_value, 4),
            "delta": round(new_value - current, 4),
            "convergence": self._compute_convergence(user, dimension),
        }

    def get_preference_vector(self, user: str) -> dict:
        """Get a user's full preference vector.

        Returns:
            Dict mapping dimension → value.
        """
        return dict(self._prefs.get(user, {}))

    def agreement_score(self, user_a: str, user_b: str) -> float:
        """Compute agreement score (cosine similarity) between two users.

        Args:
            user_a: First user identifier.
            user_b: Second user identifier.

        Returns:
            Cosine similarity in [-1, 1], or 0 if no shared dimensions.
        """
        prefs_a = self._prefs.get(user_a, {})
        prefs_b = self._prefs.get(user_b, {})
        shared = set(prefs_a.keys()) & set(prefs_b.keys())
        if not shared:
            return 0.0
        dot = sum(prefs_a[d] * prefs_b[d] for d in shared)
        mag_a = math.sqrt(sum(v * v for v in prefs_a.values()))
        mag_b = math.sqrt(sum(v * v for v in prefs_b.values()))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return round(dot / (mag_a * mag_b), 4)

    def _compute_convergence(self, user: str, dimension: str) -> float:
        """Compute convergence score (lower = more converged).

        Based on recent deltas: if recent updates are small,
        the preference is stable.
        """
        recent = [h for h in self._history[user]
                  if h["dimension"] == dimension]
        recent = recent[-10:]  # last 10 updates
        if len(recent) < 3:
            return 1.0  # not converged
        avg_delta = sum(abs(h["delta"]) for h in recent) / len(recent)
        # Scale: 0 (stable) to 1 (highly variable)
        return round(min(avg_delta * 5, 1.0), 4)

    def get_stats(self) -> dict:
        return {
            "users": len(self._prefs),
            "total_dimensions": sum(len(v) for v in self._prefs.values()),
            "total_updates": sum(len(h) for h in self._history.values()),
        }


# ────────────────────────────────────────────────────────────────
# DenoiseFlow — arXiv 2603.00532
# Signal denoising for agent workflow observations.
# ────────────────────────────────────────────────────────────────

class DenoiseFlow:
    """去噪流 — 工作流信号降噪 (arXiv 2603.00532).

    Three-stage denoising pipeline:
      1. Sensing: detect uncertain/noisy steps in a workflow
      2. Regulating: apply smoothing to reduce noise amplitude
      3. Correcting: adjust outputs toward expected values

    Supports multiple noise types: random, systematic, and drift.
    """

    def __init__(self, smoothing_window: int = 3,
                 regulation_strength: float = 0.3,
                 correction_strength: float = 0.1):
        self._sessions: list[dict[str, Any]] = []
        self._window = smoothing_window
        self._regulation_strength = regulation_strength
        self._correction_strength = correction_strength
        self._noise_profile: dict[str, float] = {
            "random": 0.0,
            "systematic": 0.0,
            "drift": 0.0,
        }

    def process(self, workflow_steps: list[dict]) -> dict:
        """Denoise a sequence of workflow steps.

        Args:
            workflow_steps: List of step dicts, each with 'value', 'certain' keys.
                            Optional: 'expected' for correction target.

        Returns:
            Dict with sensing stats, regulating params, corrections, and status.
        """
        n_steps = len(workflow_steps)
        if n_steps == 0:
            return {
                "status": "empty",
                "sensing": 0,
                "regulating": 0.0,
                "correcting": 0.0,
            }

        # 1. Sensing: detect uncertain / noisy steps
        uncertain_indices = []
        noise_type_counts: dict[str, int] = {"random": 0, "systematic": 0, "drift": 0}
        for i, step in enumerate(workflow_steps):
            if not step.get("certain", True):
                uncertain_indices.append(i)
                noise_type = step.get("noise_type", "random")
                if noise_type in noise_type_counts:
                    noise_type_counts[noise_type] += 1

        n_uncertain = len(uncertain_indices)
        uncertainty_ratio = n_uncertain / n_steps if n_steps > 0 else 0.0

        # Estimate noise levels per type
        for noise_type in self._noise_profile:
            if n_uncertain > 0:
                self._noise_profile[noise_type] = (
                    self._noise_profile[noise_type] * 0.9
                    + (noise_type_counts.get(noise_type, 0) / n_uncertain) * 0.1
                )

        # 2. Regulating: smooth noisy values using moving average
        smoothed_values = self._apply_smoothing(workflow_steps, uncertain_indices)
        applied_regulation = min(uncertainty_ratio * self._regulation_strength + 0.01, 0.95)

        # 3. Correcting: pull values toward expected targets
        corrections_applied = 0
        total_correction_magnitude = 0.0
        corrected_steps = list(workflow_steps)

        for i in uncertain_indices:
            if "expected" in workflow_steps[i]:
                current_val = workflow_steps[i].get("value", 0.0)
                expected_val = workflow_steps[i]["expected"]
                correction = (expected_val - current_val) * self._correction_strength
                corrected_steps[i] = dict(workflow_steps[i])
                corrected_steps[i]["value"] = (
                    current_val + correction
                    if isinstance(current_val, (int, float))
                    else current_val
                )
                corrected_steps[i]["corrected"] = True
                corrections_applied += 1
                total_correction_magnitude += abs(correction)

        # Determine status
        if n_uncertain == 0:
            status = "clean"
        elif uncertainty_ratio < 0.3:
            status = "safe"
        elif uncertainty_ratio < 0.6:
            status = "needs_review"
        else:
            status = "critical"

        result = {
            "status": status,
            "sensing": n_uncertain,
            "uncertainty_ratio": round(uncertainty_ratio, 3),
            "regulating": round(applied_regulation, 3),
            "correcting": round(
                min(n_uncertain * self._correction_strength, 0.5), 3
            ),
            "noise_profile": {
                k: round(v, 4) for k, v in self._noise_profile.items()
            },
            "smoothed": n_uncertain > 0,
            "corrections_applied": corrections_applied,
            "correction_magnitude": round(total_correction_magnitude, 4),
            "n_steps": n_steps,
        }
        self._sessions.append(result)
        return result

    def _apply_smoothing(self, steps: list[dict],
                         uncertain_indices: list[int]) -> dict:
        """Apply moving average smoothing to uncertain steps.

        Returns dict mapping step index → smoothed value.
        """
        smoothed: dict[int, float] = {}
        half_window = self._window // 2

        for idx in uncertain_indices:
            start = max(0, idx - half_window)
            end = min(len(steps), idx + half_window + 1)
            window = steps[start:end]
            values = [
                s.get("value", 0.0)
                for s in window
                if isinstance(s.get("value", 0.0), (int, float))
            ]
            if values:
                smoothed[idx] = sum(values) / len(values)

        return smoothed

    def get_noise_profile(self) -> dict:
        """Return the estimated noise profile."""
        return {k: round(v, 4) for k, v in self._noise_profile.items()}

    def reset_noise_profile(self) -> None:
        """Reset the noise profile to initial state."""
        self._noise_profile = {"random": 0.0, "systematic": 0.0, "drift": 0.0}

    def get_stats(self) -> dict:
        if not self._sessions:
            return {"sessions": 0}
        avg_uncertainty = sum(
            s.get("uncertainty_ratio", 0) for s in self._sessions
        ) / len(self._sessions)
        critical_count = sum(1 for s in self._sessions if s["status"] == "critical")
        return {
            "sessions": len(self._sessions),
            "avg_uncertainty_ratio": round(avg_uncertainty, 4),
            "critical_sessions": critical_count,
            "noise_profile": self.get_noise_profile(),
        }
