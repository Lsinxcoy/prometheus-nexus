"""RIMRULE-MDL — Rule Induction via Minimum Description Length.

基于:
- RIMRULE-MDL algorithm from self-evolving agent systems framework
- Minimum Description Length principle: among all rules that explain a set of
  observations, the shortest rule (in bits) is the best.
- Produces human-readable governance rules from raw system behavior patterns.

算法:
    extract_rules():
        1. Group observations by condition-outcome pairs
        2. For each pair with support >= min_support, compute MDL score
        3. MDL score = L(rule) + L(data|rule) where:
           - L(rule) = length of condition string in bits (chars * 8)
           - L(data|rule) = number of exceptions * log2(total)
        4. Sort rules by MDL score (ascending, lower = better)
        5. Keep top max_rules

Usage:
    rimrule = RIMRULE()
    rimrule.add_observation({"condition": "high_memory_usage", "outcome": "gc_run", "utility": 0.8})
    rules = rimrule.extract_rules()
    prediction = rimrule.predict("high_memory_usage")
"""

from __future__ import annotations

import logging
import math
import time
import uuid

logger = logging.getLogger(__name__)


class RIMRULE:
    """Rule Induction via Minimum Description Length.

    Automatically extracts compact, interpretable rules from behavioral data
    using the MDL principle.

    Usage:
        rimrule = RIMRULE(max_rules=50, min_support=3)
        rimrule.add_observation({"condition": "error_rate>0.1", "outcome": "rollback", "utility": 0.7})
        rules = rimrule.extract_rules()
        top_rules = rimrule.get_rules(sort_by="confidence", limit=5)
        result = rimrule.predict("error_rate>0.1")
    """

    def __init__(self, max_rules: int = 50, min_support: int = 3):
        self._rules: list[dict] = []
        self._training_data: list[dict] = []
        self._mdl_scores: dict[str, float] = {}
        self._max_rules: int = max_rules
        self._min_support: int = min_support

        # R1: Adaptive MDL Thresholds
        self._mdl_trend: list[float] = []
        self._rule_quality_history: list[float] = []  # rolling accuracy window (0.0=wrong, 1.0=correct)
        self._min_support_adaptive: int = self._min_support
        self._max_rules_adaptive: int = self._max_rules
        self._adaptation_rate: float = 0.1
        self._quality_window: int = 20

        # R2: Prediction-Error Feedback Loop
        self._last_predictions: dict[str, dict] = {}

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    def add_observation(self, data: dict) -> int:
        """Add a raw observation for rule learning.

        Args:
            data: Must contain {"condition": str, "outcome": str, "utility": float}.

        Returns:
            Total observation count after adding.
        """
        self._training_data.append(data)
        return len(self._training_data)

    def extract_rules(
        self,
        min_support: int | None = None,
        observation_weights: dict[str, float] | None = None,
    ) -> list[dict]:
        """Run the RIMRULE-MDL algorithm on accumulated observations.

        Steps:
            1. Group observations by condition-outcome pairs.
            2. For each pair with support >= min_support, compute MDL score.
            3. MDL score = L(rule) + L(data|rule) where:
               - L(rule) = length of condition string in bits (chars * 8)
               - L(data|rule) = number of effective exceptions * log2(total)
            4. Effective exceptions are scaled by observation utility:
               high-utility conditions → fewer effective exceptions (lower MDL).
            5. Sort rules by MDL score (ascending, lower = better).
            6. Keep top max_rules.

        Args:
            min_support: Override the instance default min_support for this run.
            observation_weights: Optional dict mapping condition strings to
                weight values (0.0-1.0). High-weight conditions produce fewer
                effective exceptions and lower MDL scores.

        Returns:
            Sorted list of extracted rule dicts.
        """
        effective_min_support = self._min_support_adaptive if min_support is None else min_support
        total = len(self._training_data)

        if total == 0:
            self._rules = []
            self._mdl_scores = {}
            return []

        # 1. Group observations by condition-outcome pairs
        pair_groups: dict[tuple[str, str], list[dict]] = {}
        condition_counts: dict[str, int] = {}

        for obs in self._training_data:
            condition = obs.get("condition", "")
            outcome = obs.get("outcome", "")
            key = (condition, outcome)
            pair_groups.setdefault(key, []).append(obs)
            condition_counts[condition] = condition_counts.get(condition, 0) + 1

        # 2. Compute MDL for each qualifying pair
        candidate_rules: list[dict] = []

        for (condition, action), observations in pair_groups.items():
            support = len(observations)
            if support < effective_min_support:
                continue

            total_for_condition = condition_counts.get(condition, 0)
            exceptions = total_for_condition - support

            # --- R4: Observation Weighting by Utility ---
            # Compute average utility of observations for this condition
            avg_utility = sum(
                o.get("utility", 0.5) for o in observations
            ) / len(observations)

            # If observation_weights provided for this condition, override
            if observation_weights and condition in observation_weights:
                avg_utility = observation_weights[condition]

            # Scale exception count: high utility → lower effective exceptions
            effective_exceptions = exceptions * (1.0 + (1.0 - avg_utility) * 0.5)
            # ---------------------------------------------

            # MDL score
            l_rule = len(condition) * 8  # bits
            l_data_given_rule = effective_exceptions * (math.log2(total) if total > 1 else 0)
            mdl_score = l_rule + l_data_given_rule

            confidence = support / max(total_for_condition, 1)

            rule = {
                "id": str(uuid.uuid4())[:8],
                "condition": condition,
                "action": action,
                "mdl_score": round(mdl_score, 4),
                "support": support,
                "confidence": round(confidence, 4),
                "created_at": time.time(),
                # R3: fields for rule aging / quality tracking
                "last_checked": time.time(),
                "correct_count": 0,
                "total_checks": 0,
                # R4: weighted exceptions for transparency
                "weighted_exceptions": round(effective_exceptions, 4),
                "avg_observation_weight": round(avg_utility, 4),
            }
            candidate_rules.append(rule)

        # 3. Sort by MDL score ascending
        candidate_rules.sort(key=lambda r: r["mdl_score"])

        # 4. Keep top max_rules_adaptive
        self._rules = candidate_rules[: self._max_rules_adaptive]

        # 5. Update mdl_scores index
        self._mdl_scores = {r["id"]: r["mdl_score"] for r in self._rules}

        # R1: Record avg MDL trend
        if self._rules:
            avg_mdl = sum(r["mdl_score"] for r in self._rules) / len(self._rules)
            self._mdl_trend.append(avg_mdl)

        # R1: Adapt thresholds based on rule quality history
        self._adapt_thresholds()

        return list(self._rules)

    def get_rules(self, sort_by: str = "mdl", limit: int = 10) -> list[dict]:
        """Get extracted rules sorted by the given criterion.

        Args:
            sort_by: "mdl" (ascending) or "confidence" (descending).
            limit: Maximum number of rules to return.

        Returns:
            List of rule dicts.
        """
        if sort_by == "confidence":
            sorted_rules = sorted(self._rules, key=lambda r: r.get("confidence", 0), reverse=True)
        else:
            # Default: sort by mdl ascending
            sorted_rules = sorted(self._rules, key=lambda r: r.get("mdl_score", float("inf")))

        return sorted_rules[:limit]

    def predict(self, condition: str) -> dict:
        """Find the best matching rule for a given condition.

        Match priority:
            1. Exact match (rule.condition == condition)
            2. Substring containment (condition in rule.condition or vice versa)
            3. Highest-confidence rule among all remaining

        Args:
            condition: The condition string to match.

        Returns:
            {"prediction": str, "rule_id": str, "confidence": float, "mdl_score": float}
            or {"prediction": "unknown", "confidence": 0.0} if no match.
        """
        if not self._rules:
            result = {"prediction": "unknown", "confidence": 0.0}
            self._cache_prediction(condition, result)
            return result

        # Pass 1: Exact match
        for rule in self._rules:
            if rule.get("condition", "") == condition:
                result = {
                    "prediction": rule["action"],
                    "rule_id": rule["id"],
                    "confidence": rule.get("confidence", 0.0),
                    "mdl_score": rule.get("mdl_score", 0.0),
                }
                self._cache_prediction(condition, result)
                return result

        # Pass 2: Substring containment
        for rule in self._rules:
            rc = rule.get("condition", "")
            if condition in rc or rc in condition:
                result = {
                    "prediction": rule["action"],
                    "rule_id": rule["id"],
                    "confidence": rule.get("confidence", 0.0),
                    "mdl_score": rule.get("mdl_score", 0.0),
                }
                self._cache_prediction(condition, result)
                return result

        # Pass 3: Highest-confidence rule
        best = max(self._rules, key=lambda r: r.get("confidence", 0))
        if best.get("confidence", 0) > 0:
            result = {
                "prediction": best["action"],
                "rule_id": best["id"],
                "confidence": best.get("confidence", 0.0),
                "mdl_score": best.get("mdl_score", 0.0),
            }
            self._cache_prediction(condition, result)
            return result

        result = {"prediction": "unknown", "confidence": 0.0}
        self._cache_prediction(condition, result)
        return result

    # ------------------------------------------------------------------
    #  R2: Prediction-Error Feedback Loop
    # ------------------------------------------------------------------

    def _cache_prediction(self, condition: str, prediction: dict) -> None:
        """Store the last prediction for a condition so that report_outcome()
        can retrieve it even before the next extract_rules() call.

        Args:
            condition: The condition string that was predicted.
            prediction: The prediction dict returned by predict().
        """
        self._last_predictions[condition] = prediction

    def report_outcome(self, condition: str, actual_outcome: str) -> dict:
        """Report the actual outcome for a previous prediction, updating the
        matching rule's confidence, MDL score, and quality history.

        Steps:
            1. Call predict(condition) to get the predicted outcome.
            2. Compare predicted vs actual.
            3. Find the matching rule and update its fields.
            4. Append to quality history and trigger threshold adaptation.

        Args:
            condition: The condition string that was predicted.
            actual_outcome: The actual outcome string that occurred.

        Returns:
            {"condition": str, "predicted": str, "actual": str,
             "correct": bool, "rule_id": str | None}
        """
        prediction = self.predict(condition)
        predicted = prediction.get("prediction", "unknown")
        rule_id = prediction.get("rule_id")
        was_correct = (predicted == actual_outcome)

        # Find the matching rule (by rule_id, or by condition fallback)
        matched_rule = None
        if rule_id:
            for r in self._rules:
                if r["id"] == rule_id:
                    matched_rule = r
                    break

        if matched_rule:
            old_conf = matched_rule.get("confidence", 0.0)
            matched_rule["total_checks"] = matched_rule.get("total_checks", 0) + 1
            if was_correct:
                matched_rule["correct_count"] = matched_rule.get("correct_count", 0) + 1

            # EMA update: new_conf = old_conf + 0.3 * (target - old_conf)
            target = 1.0 if was_correct else 0.0
            matched_rule["confidence"] = round(old_conf + 0.3 * (target - old_conf), 4)

            matched_rule["last_checked"] = time.time()

            if not was_correct:
                matched_rule["mdl_score"] = round(matched_rule.get("mdl_score", 0.0) * 1.05, 4)

        # Record in quality history
        self._rule_quality_history.append(1.0 if was_correct else 0.0)

        # Adapt thresholds based on updated quality history
        self._adapt_thresholds()

        return {
            "condition": condition,
            "predicted": predicted,
            "actual": actual_outcome,
            "correct": was_correct,
            "rule_id": rule_id,
        }

    def evaluate_rule(self, rule_id: str, test_data: list[dict]) -> dict:
        """Evaluate a specific rule against test data.

        Args:
            rule_id: The id of the rule to evaluate.
            test_data: List of observations with {"condition": str, "outcome": str, ...}.

        Returns:
            {"correct": int, "total": int, "accuracy": float,
             "precision": float, "recall": float}
        """
        # Find the rule
        target_rule = None
        for r in self._rules:
            if r["id"] == rule_id:
                target_rule = r
                break

        if target_rule is None:
            return {"correct": 0, "total": 0, "accuracy": 0.0, "precision": 0.0, "recall": 0.0}

        condition = target_rule["condition"]
        action = target_rule["action"]

        tp = 0
        fp = 0
        fn = 0
        tn = 0

        for datum in test_data:
            cond_matches = datum.get("condition", "") == condition
            outcome_matches = datum.get("outcome", "") == action

            if cond_matches and outcome_matches:
                tp += 1
            elif cond_matches and not outcome_matches:
                fp += 1
            elif not cond_matches and outcome_matches:
                fn += 1
            else:
                tn += 1

        total = len(test_data)
        correct = tp + tn
        accuracy = correct / max(total, 1)
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)

        return {
            "correct": correct,
            "total": total,
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
        }

    def get_stats(self) -> dict:
        """Return aggregate statistics.

        Includes avg_observation_weight when any rule has weighted_exceptions.
        """
        total_rules = len(self._rules)
        total_observations = len(self._training_data)

        if total_rules == 0:
            return {
                "total_rules": 0,
                "total_observations": total_observations,
                "avg_mdl_score": 0.0,
                "avg_confidence": 0.0,
                "avg_support": 0.0,
            }

        avg_mdl = sum(r.get("mdl_score", 0) for r in self._rules) / total_rules
        avg_conf = sum(r.get("confidence", 0) for r in self._rules) / total_rules
        avg_sup = sum(r.get("support", 0) for r in self._rules) / total_rules

        result: dict = {
            "total_rules": total_rules,
            "total_observations": total_observations,
            "avg_mdl_score": round(avg_mdl, 4),
            "avg_confidence": round(avg_conf, 4),
            "avg_support": round(avg_sup, 4),
        }

        # R4: Include avg_observation_weight when available
        weight_vals = [
            r["avg_observation_weight"]
            for r in self._rules
            if r.get("avg_observation_weight") is not None
        ]
        if weight_vals:
            result["avg_observation_weight"] = round(
                sum(weight_vals) / len(weight_vals), 4
            )

        return result

    # ------------------------------------------------------------------
    #  R1: Adaptive MDL Thresholds
    # ------------------------------------------------------------------

    def _adapt_thresholds(self) -> None:
        """Adjust min_support and max_rules based on recent rule quality trend.

        If quality is degrading (trend < -0.05), relax thresholds to allow more rules.
        If quality is improving (trend > 0.05), tighten thresholds to be more selective.
        """
        if len(self._rule_quality_history) < self._quality_window:
            return

        recent = self._rule_quality_history[-self._quality_window :]
        trend = (recent[-1] - recent[0]) / len(recent)

        if trend < -0.05:
            # Degrading → relax
            self._min_support_adaptive = max(1, self._min_support_adaptive - 1)
            self._max_rules_adaptive = min(200, self._max_rules_adaptive + 10)
        elif trend > 0.05:
            # Improving → tighten
            self._min_support_adaptive = min(10, self._min_support_adaptive + 1)
            self._max_rules_adaptive = max(10, self._max_rules_adaptive - 10)

    # ------------------------------------------------------------------
    #  R3: Rule Aging and Pruning
    # ------------------------------------------------------------------

    def prune_rules(
        self, max_age_seconds: float = 604800, min_confidence: float = 0.1
    ) -> int:
        """Remove stale or low-confidence rules.

        Args:
            max_age_seconds: Maximum age (seconds since last_checked) before a rule
                             is considered stale. Default 7 days.
            min_confidence: Minimum confidence threshold. Rules below this value
                            are pruned.

        Returns:
            Number of rules pruned.
        """
        now = time.time()
        before = len(self._rules)

        self._rules = [
            r
            for r in self._rules
            if not (
                r.get("total_checks", 0) >= 5
                and (
                    now - r.get("last_checked", now) > max_age_seconds
                    or r.get("confidence", 0.0) < min_confidence
                )
            )
        ]

        # Also trim training_data — if over 10k keep last 5k
        if len(self._training_data) > 10000:
            self._training_data = self._training_data[-5000:]

        pruned = before - len(self._rules)
        if pruned:
            logger.debug("prune_rules: removed %d rules", pruned)
        return pruned
