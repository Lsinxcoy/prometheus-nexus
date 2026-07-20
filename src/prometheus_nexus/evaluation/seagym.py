"""SEAGym — Self-evolving agent evaluation environment.

Based on: "SEAGym: An Evaluation Environment for Self-Evolving LLM Agents"
(arXiv:2606.17546, Zheng et al. 2026)

Key Concepts from Paper:
    1. Train/Validation/Test split for evolution evaluation
    2. Frozen update-validation (prevents overfitting to recent tasks)
    3. ID/OOD transfer views (in-distribution vs out-of-distribution)
    4. Replay diagnostics (identify collapsed snapshots)
    5. Snapshot management (save/restore evolution states)
    6. Cost records (token consumption tracking)
    7. Harness update evaluation (not just task scores)

Paper Finding:
    "Frequent updates may fail to improve held-out performance,
     useful intermediate snapshots may collapse later,
     and source diversity and model backend can affect harness reliability."

Algorithm:
    - Maintain train/val/test splits
    - Track evolution snapshots with metrics
    - Detect overfitting via val/test divergence
    - Replay diagnostics for snapshot comparison
    - Cost tracking for efficiency analysis

Complexity:
    evaluate(): O(N) where N = test cases
    save_snapshot(): O(S) where S = snapshot size
    replay(): O(N × S)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalCase:
    """A single evaluation case."""
    id: str = ""
    input_data: Any = None
    expected_output: Any = None
    split: str = "test"  # train/val/test
    category: str = ""


@dataclass
class EvalResult:
    """Result of evaluating a single case."""
    case_id: str = ""
    score: float = 0.0
    passed: bool = False
    latency_ms: float = 0.0
    tokens_used: int = 0
    details: dict = field(default_factory=dict)


@dataclass
class Snapshot:
    """An evolution snapshot with metrics."""
    id: str = ""
    epoch: int = 0
    timestamp: float = 0.0
    train_scores: dict = field(default_factory=dict)
    val_scores: dict = field(default_factory=dict)
    test_scores: dict = field(default_factory=dict)
    cost_tokens: int = 0
    metadata: dict = field(default_factory=dict)


class SEAGym:
    """Self-evolution evaluation environment.

    Based on SEAGym paper (arXiv:2606.17546).

    Usage:
        gym = SEAGym()

        # Register evaluation cases
        gym.register_case(EvalCase(id="c1", input_data="q1", expected_output="a1", split="train"))
        gym.register_case(EvalCase(id="c2", input_data="q2", expected_output="a2", split="val"))
        gym.register_case(EvalCase(id="c3", input_data="q3", expected_output="a3", split="test"))

        # Evaluate
        results = gym.evaluate(lambda x: "a1")  # evaluator function
        snapshot = gym.save_snapshot(epoch=1)

        # Analyze
        overfitting = gym.detect_overfitting()
        replay_results = gym.replay(snapshot)
    """

    def __init__(self):
        self._cases: list[EvalCase] = []
        self._snapshots: list[Snapshot] = []
        self._current_epoch = 0
        self._total_tokens = 0
        self._evaluation_history: list[dict] = []

    def register_case(self, case: EvalCase) -> None:
        """Register an evaluation case."""
        self._cases.append(case)

    def register_cases(self, cases: list[EvalCase]) -> None:
        """Register multiple evaluation cases."""
        self._cases.extend(cases)

    def evaluate(self, evaluator: callable | str | None = None, split: str | None = None,
                 limit: int | None = None) -> list[EvalResult] | dict:
        """Evaluate cases with the given evaluator function.

        Args:
            evaluator: Function that takes input_data and returns predicted output.
                       If string, records the evaluation context (backward-compatible).
            split: If specified, only evaluate cases in this split.
            limit: Maximum cases to evaluate.

        Returns:
            List of EvalResult objects, or dict if string evaluator (backward-compat).
        """
        # Backward-compatible: if evaluator is a string, just record the context
        if isinstance(evaluator, str):
            self._evaluation_history.append({
                "epoch": self._current_epoch,
                "timestamp": time.time(),
                "context": evaluator,
                "split_scores": {},
                "total_cases": 0,
                "pass_rate": 0,
            })
            return []

        if evaluator is None:
            return []

        cases = self._cases
        if split:
            cases = [c for c in cases if c.split == split]
        if limit and isinstance(limit, int):
            cases = cases[:limit]

        results = []
        for case in cases:
            start = time.time()
            try:
                predicted = evaluator(case.input_data)
                score = 1.0 if predicted == case.expected_output else 0.0
                passed = score > 0.5
            except Exception as e:
                score = 0.0
                passed = False
                predicted = None

            elapsed_ms = (time.time() - start) * 1000
            result = EvalResult(
                case_id=case.id, score=score, passed=passed,
                latency_ms=elapsed_ms, details={"predicted": predicted},
            )
            results.append(result)

        # Record evaluation
        split_scores = {}
        for r in results:
            case = next((c for c in cases if c.id == r.case_id), None)
            if case:
                split_scores.setdefault(case.split, []).append(r.score)

        eval_record = {
            "epoch": self._current_epoch,
            "timestamp": time.time(),
            "split_scores": {s: sum(sc) / len(sc) for s, sc in split_scores.items()},
            "total_cases": len(results),
            "pass_rate": sum(1 for r in results if r.passed) / max(len(results), 1),
        }
        self._evaluation_history.append(eval_record)

        return results

    def evaluate_all_splits(self, evaluator: callable) -> dict[str, list[EvalResult]]:
        """Evaluate all splits separately.

        Returns:
            Dict mapping split name to evaluation results.
        """
        results = {}
        for split in ["train", "val", "test"]:
            split_cases = [c for c in self._cases if c.split == split]
            if split_cases:
                results[split] = self.evaluate(evaluator, split=split)
        return results

    def save_snapshot(self, epoch: int | None = None, metadata: dict | None = None) -> Snapshot:
        """Save an evolution snapshot with current metrics.

        Args:
            epoch: Epoch number (auto-increments if None).
            metadata: Additional metadata to save.

        Returns:
            Snapshot object.
        """
        if epoch is None:
            self._current_epoch += 1
            epoch = self._current_epoch
        else:
            self._current_epoch = max(self._current_epoch, epoch)

        # Compute split scores from history
        train_scores = {}
        val_scores = {}
        test_scores = {}

        for record in self._evaluation_history[-1:]:
            for split, score in record.get("split_scores", {}).items():
                if split == "train":
                    train_scores[f"epoch_{epoch}"] = score
                elif split == "val":
                    val_scores[f"epoch_{epoch}"] = score
                elif split == "test":
                    test_scores[f"epoch_{epoch}"] = score

        snapshot = Snapshot(
            id=f"snapshot_{epoch}_{int(time.time())}",
            epoch=epoch, timestamp=time.time(),
            train_scores=train_scores, val_scores=val_scores,
            test_scores=test_scores, cost_tokens=self._total_tokens,
            metadata=metadata or {},
        )
        self._snapshots.append(snapshot)
        return snapshot

    def detect_overfitting(self, window: int = 3) -> dict:
        """Detect overfitting by comparing train/val/test trends.

        From SEAGym paper: "frequent updates may fail to improve
        held-out performance."

        Returns:
            Dict with overfitting analysis.
        """
        if len(self._evaluation_history) < window:
            return {"overfitting_detected": False, "reason": "insufficient_history"}

        recent = self._evaluation_history[-window:]
        train_trend = [r.get("split_scores", {}).get("train", 0) for r in recent]
        val_trend = [r.get("split_scores", {}).get("val", 0) for r in recent]
        test_trend = [r.get("split_scores", {}).get("test", 0) for r in recent]

        # Check if train improves but val/test decline
        train_improving = len(train_trend) >= 2 and train_trend[-1] > train_trend[0]
        val_declining = len(val_trend) >= 2 and val_trend[-1] < val_trend[0]
        test_declining = len(test_trend) >= 2 and test_trend[-1] < test_trend[0]

        overfitting = train_improving and (val_declining or test_declining)

        # Check for snapshot collapse
        snapshot_collapse = False
        if len(self._snapshots) >= 2:
            recent_val = self._snapshots[-1].val_scores
            prev_val = self._snapshots[-2].val_scores
            if recent_val and prev_val:
                recent_avg = sum(recent_val.values()) / len(recent_val)
                prev_avg = sum(prev_val.values()) / len(prev_val)
                if recent_avg < prev_avg * 0.8:
                    snapshot_collapse = True

        return {
            "overfitting_detected": overfitting,
            "snapshot_collapse": snapshot_collapse,
            "train_trend": train_trend,
            "val_trend": val_trend,
            "test_trend": test_trend,
        }

    def replay(self, snapshot: Snapshot, evaluator: callable | None = None) -> dict:
        """Replay a snapshot's evaluation for diagnostics.

        From SEAGym paper: "replay diagnostics for snapshot comparison."

        Returns:
            Dict with replay results.
        """
        if evaluator:
            results = self.evaluate(evaluator, split="test")
            current_scores = {r.case_id: r.score for r in results}
        else:
            current_scores = snapshot.test_scores

        return {
            "snapshot_id": snapshot.id,
            "epoch": snapshot.epoch,
            "snapshot_scores": snapshot.test_scores,
            "current_scores": current_scores,
            "score_change": {k: current_scores.get(k, 0) - v
                             for k, v in snapshot.test_scores.items()},
        }

    def get_cost_analysis(self) -> dict:
        """Analyze cost across snapshots."""
        if not self._snapshots:
            return {"total_snapshots": 0}

        costs = [s.cost_tokens for s in self._snapshots]
        return {
            "total_snapshots": len(self._snapshots),
            "total_tokens": sum(costs),
            "avg_tokens_per_snapshot": sum(costs) / len(costs),
            "token_trend": costs,
        }

    def get_transfer_analysis(self) -> dict:
        """Analyze ID vs OOD transfer performance."""
        id_scores = []
        ood_scores = []
        for record in self._evaluation_history:
            for split, score in record.get("split_scores", {}).items():
                if split == "test":
                    id_scores.append(score)
                elif split == "val":
                    ood_scores.append(score)

        return {
            "id_avg": sum(id_scores) / max(len(id_scores), 1),
            "ood_avg": sum(ood_scores) / max(len(ood_scores), 1),
            "transfer_gap": (sum(id_scores) / max(len(id_scores), 1)) -
                           (sum(ood_scores) / max(len(ood_scores), 1)),
        }

    def get_stats(self) -> dict:
        """Get evaluation statistics."""
        return {
            "total_cases": len(self._cases),
            "cases_by_split": {s: sum(1 for c in self._cases if c.split == s)
                              for s in ["train", "val", "test"]},
            "snapshots": len(self._snapshots),
            "evaluations": len(self._evaluation_history),
            "current_epoch": self._current_epoch,
            "total_tokens": self._total_tokens,
        }
