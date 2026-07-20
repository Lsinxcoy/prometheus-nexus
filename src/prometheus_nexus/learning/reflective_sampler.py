"""ReflectiveSampler — RareDxR1 反思增强推理 (arXiv 2607.00147).

RERS: Reflection-Enhanced Reasoning Sampling.
Synthesizes expert-level trajectories via dual-level curriculum RL from failure paths.
Key mechanisms:
  - Failure cluster tracking: group similar failures by error signature
  - Priority scoring: rank clusters by error frequency × recency
  - Structured reflective example generation: extract lessons + corrected paths
  - Adaptive sampling weights: more weight to high-value failure clusters
"""
from __future__ import annotations

import logging
import math
import time
from collections import Counter, defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def _error_signature(error: str) -> str:
    """Extract a normalized error signature for cluster grouping."""
    if not error:
        return "empty_error"
    # Normalize: lowercase, strip whitespace, collapse numbers
    sig = error.lower().strip()
    for token in ["execution error", "runtime error", "valueerror", "typeerror",
                   "keyerror", "attributeerror", "indexerror", "importerror",
                   "modulenotfounderror", "timeout", "syntaxerror", "oserror",
                   "filenotfounderror", "zerodivisionerror", "stopiteration"]:
        if token in sig:
            return token
    # Fall back to first 40 chars as signature
    return sig[:40]


def _task_type(task: str) -> str:
    """Classify task into a type for cross-cluster analysis."""
    t = task.lower()
    if "code" in t or "program" in t or "implement" in t or "write" in t:
        return "code_generation"
    if "reason" in t or "think" in t or "logic" in t or "math" in t:
        return "reasoning"
    if "search" in t or "retrieve" in t or "find" in t:
        return "retrieval"
    if "plan" in t or "decompose" in t:
        return "planning"
    if "summar" in t or "summarize" in t or "extract" in t:
        return "summarization"
    return "general"


class FailureCluster:
    """A cluster of similar failures with priority scoring."""

    def __init__(self, signature: str, task_type: str):
        self.signature = signature
        self.task_type = task_type
        self.failures: list[dict] = []
        self.first_seen = time.time()
        self.last_seen = time.time()
        self.total_count = 0

    def add_failure(self, path: dict) -> None:
        """Add a failure path to this cluster."""
        self.failures.append(path)
        self.total_count += 1
        self.last_seen = time.time()

    @property
    def priority_score(self) -> float:
        """Score based on frequency × recency weight.

        Higher frequency + more recent = higher priority.
        Uses log-frequency to avoid runaway dominance by one cluster.
        """
        if self.total_count == 0:
            return 0.0
        frequency = math.log1p(self.total_count)  # log(1 + n)
        age_hours = (time.time() - self.first_seen) / 3600.0
        recency = math.exp(-age_hours / 24.0)  # half-life ~ 24h
        return frequency * recency

    def generate_reflective_example(self, max_examples: int = 3) -> dict:
        """Generate a structured reflective example from this cluster.

        Returns a dict with lessons, a corrected trajectory sketch,
        and a counter-example from the most common failure.
        """
        if not self.failures:
            return {"lessons": [], "corrected_trajectory": [], "counter_example": {}}

        # Extract common error patterns
        errors = [f.get("error", "") for f in self.failures]
        error_counter = Counter(str(e) for e in errors if e)
        most_common_error = error_counter.most_common(1)[0][0] if error_counter else ""

        # Extract tasks for context
        tasks = [f.get("task", "") for f in self.failures[:max_examples]]

        # Synthesize lessons
        lessons = []
        if "timeout" in str(most_common_error).lower():
            lessons.append("Task exceeds time limit — decompose into smaller subtasks")
            lessons.append("Use iterative deepening with early termination checks")
        if "invalid" in str(most_common_error).lower() or "error" in str(most_common_error).lower():
            lessons.append("Output validation step required before proceeding")
            lessons.append("Add defensive checks at each intermediate stage")
        if self.task_type == "code_generation":
            lessons.append("Prefer incremental implementation with test-after-each-step")
        elif self.task_type == "reasoning":
            lessons.append("Break reasoning into explicit intermediate steps")
            lessons.append("Verify each deduction before building on it")
        else:
            lessons.append(f"Failure signature '{self.signature[:40]}' — add guard against this pattern")

        # Build a corrected trajectory sketch
        corrected_trajectory = []
        for i, task in enumerate(tasks[:max_examples]):
            corrected_trajectory.append({
                "step": i,
                "original_task": task[:100],
                "corrected_approach": f"Avoid {self.signature[:50]} — "
                                      f"{lessons[i] if i < len(lessons) else 'general caution'}",
            })

        return {
            "cluster_signature": self.signature,
            "task_type": self.task_type,
            "frequency": self.total_count,
            "priority": round(self.priority_score, 4),
            "lessons": lessons,
            "corrected_trajectory": corrected_trajectory,
            "counter_example": {
                "error": most_common_error[:200],
                "n_occurrences": error_counter.get(most_common_error, 0),
            },
        }


class DualLevelCurriculumRL:
    """Dual-level curriculum reinforcement learning.

    Implements the RERS dual-level curriculum:
      *Micro-level*: per-step difficulty progression within a trajectory.
      *Macro-level*: across trajectories — easy → hard task sequencing.

    Difficulty is based on task type, error rate, and step complexity.
    """

    def __init__(self) -> None:
        self._task_difficulty: dict[str, float] = {}  # task_type -> difficulty estimate
        self._step_difficulty: dict[str, list[float]] = defaultdict(list)  # task_type -> [step scores]
        self._curriculum_stage: int = 0  # current macro curriculum stage

    # ── Micro-level (per-step) ──────────────────────────────────

    def score_step_difficulty(self, step: dict) -> float:
        """Score the difficulty of a single reasoning step (0.0=easy, 1.0=hard)."""
        score = 0.0
        if step.get("error"):
            score += 0.3
        if len(step.get("content", "")) > 500:
            score += 0.1
        if step.get("requires_search") or step.get("requires_tool"):
            score += 0.2
        if step.get("intermediate_steps", 0) > 3:
            score += 0.2
        return min(1.0, score)

    def register_step(self, task_type: str, step: dict) -> None:
        """Register a step's difficulty for micro-curriculum tracking."""
        diff = self.score_step_difficulty(step)
        self._step_difficulty[task_type].append(diff)

    def micro_curriculum_weight(self, task_type: str, step_idx: int) -> float:
        """Return how much to weight this step given micro-curriculum progress.

        Early steps get higher weight (foundational), later steps get
        lower weight unless they are harder.
        """
        steps = self._step_difficulty.get(task_type, [])
        if not steps or step_idx >= len(steps):
            return 0.5  # default
        # Progression principle: start easy, gradually increase
        difficulty = steps[step_idx]
        progression = step_idx / max(len(steps), 1)
        # Steps that are both late AND hard get weight boost
        if difficulty > 0.5 and progression > 0.5:
            return min(1.0, difficulty + progression)
        return max(0.2, 1.0 - progression * 0.5)

    # ── Macro-level (across trajectories) ──────────────────────

    def estimate_task_difficulty(self, task: str, error: str) -> float:
        """Estimate task-level difficulty from task description and error."""
        diff = 0.0
        t = task.lower()
        if "complex" in t or "multi-step" in t or "multi" in t:
            diff += 0.3
        if "research" in t or "analysis" in t or "synthesis" in t:
            diff += 0.2
        if "code" in t or "program" in t:
            diff += 0.15
        if "timeout" in error.lower():
            diff += 0.25
        if "error" in error.lower() or "invalid" in error.lower():
            diff += 0.1
        return min(1.0, diff)

    def update_task_difficulty(self, task_type: str, task: str, error: str) -> None:
        """Update macro-level task difficulty estimate."""
        diff = self.estimate_task_difficulty(task, error)
        old = self._task_difficulty.get(task_type, 0.0)
        # EMA update
        self._task_difficulty[task_type] = 0.7 * old + 0.3 * diff

    def curriculum_schedule(self) -> dict:
        """Return the current curriculum schedule.

        Tasks ordered by difficulty so the sampler can select
        appropriately challenging tasks at each curriculum stage.
        """
        if not self._task_difficulty:
            return {"stage": 0, "easy": 1.0, "medium": 0.0, "hard": 0.0}

        sorted_types = sorted(self._task_difficulty.items(), key=lambda x: x[1])
        return {
            "stage": self._curriculum_stage,
            "task_types_by_difficulty": [t for t, _ in sorted_types],
            "easy_pct": sum(1 for _, d in sorted_types if d < 0.3) / max(len(sorted_types), 1),
            "medium_pct": sum(1 for _, d in sorted_types if 0.3 <= d < 0.7) / max(len(sorted_types), 1),
            "hard_pct": sum(1 for _, d in sorted_types if d >= 0.7) / max(len(sorted_types), 1),
        }

    def advance_stage(self) -> int:
        """Advance to the next macro curriculum stage."""
        self._curriculum_stage += 1
        return self._curriculum_stage


class KnowledgeInternalization:
    """Knowledge internalization: distill lessons into reusable knowledge snippets.

    Instead of keeping raw failure paths, this component extracts
    abstract, task-type-agnostic knowledge that can be reused across
    different reasoning contexts.

    Key mechanism:
      1. Extract lessons from failure clusters
      2. Generalize lessons across task types (cross-task transfer)
      3. Store as compact, reusable knowledge snippets
      4. Apply knowledge snippets during new reasoning attempts
    """

    def __init__(self) -> None:
        self._knowledge_base: dict[str, list[dict]] = defaultdict(list)  # category -> [snippets]
        self._cross_task_transfer: dict[str, set[str]] = defaultdict(set)  # source_type -> {target_types}
        self._total_internalized: int = 0

    # ── Internalization ────────────────────────────────────────

    def internalize(self, cluster: FailureCluster) -> list[dict]:
        """Internalize lessons from a failure cluster into knowledge snippets.

        Returns list of knowledge snippets: [{'category', 'principle', 'source_type', 'confidence'}, ...]
        """
        if not cluster.failures:
            return []

        snippets: list[dict] = []

        # Extract common error patterns
        errors = [f.get("error", "") for f in cluster.failures if f.get("error")]
        error_counter = Counter(str(e) for e in errors)
        if not error_counter:
            return []

        most_common_err = error_counter.most_common(1)[0][0]

        # Generate knowledge snippets from error patterns
        err_lower = str(most_common_err).lower()

        # Timing/efficiency knowledge
        if "timeout" in err_lower:
            snippets.append({
                "category": "efficiency",
                "principle": "Decompose timeout-prone tasks into smaller subtasks with intermediate verification.",
                "source_type": cluster.task_type,
                "confidence": 0.85,
            })

        # Validation knowledge
        if "error" in err_lower or "invalid" in err_lower or "valueerror" in err_lower:
            snippets.append({
                "category": "validation",
                "principle": "Add intermediate output validation after each step before proceeding to the next.",
                "source_type": cluster.task_type,
                "confidence": 0.8,
            })

        # Code-specific knowledge
        if cluster.task_type == "code_generation":
            snippets.append({
                "category": "code",
                "principle": "Prefer incremental implementation with per-function testing over monolithic generation.",
                "source_type": cluster.task_type,
                "confidence": 0.9,
            })

        # Reasoning-specific knowledge
        if cluster.task_type == "reasoning":
            snippets.append({
                "category": "reasoning",
                "principle": "Explicitly verify each intermediate deduction before using it as a premise for the next.",
                "source_type": cluster.task_type,
                "confidence": 0.85,
            })

        # Task-type-specific knowledge from cluster signature
        if cluster.task_type == "planning":
            snippets.append({
                "category": "planning",
                "principle": "Generate at least 3 alternative decomposition strategies before selecting one.",
                "source_type": cluster.task_type,
                "confidence": 0.75,
            })

        # Generic fallback knowledge
        if not snippets:
            snippets.append({
                "category": "general",
                "principle": f"Guard against failure pattern: {cluster.signature[:60]}",
                "source_type": cluster.task_type,
                "confidence": 0.6,
            })

        # Store in knowledge base
        for s in snippets:
            self._knowledge_base[s["category"]].append(s)
            self._total_internalized += 1

        # Update cross-task transfer: knowledge from this task type may apply to others
        # E.g., validation knowledge applies to all task types
        if any(s["category"] == "validation" for s in snippets):
            all_types = {"code_generation", "reasoning", "planning", "retrieval", "summarization", "general"}
            self._cross_task_transfer[cluster.task_type].update(all_types - {cluster.task_type})

        return snippets

    def get_relevant_knowledge(self, task_type: str, task: str, top_k: int = 5) -> list[dict]:
        """Retrieve the most relevant knowledge snippets for a given task type/task.

        Applies cross-task transfer: if task_type X has transferrable knowledge
        to task_type Y, snippets from X are also considered.
        """
        candidates: list[dict] = []

        # Direct knowledge
        for category, snippets in self._knowledge_base.items():
            for s in snippets:
                if s["source_type"] == task_type:
                    candidates.append(s)

        # Cross-task transferred knowledge
        for source_type, target_types in self._cross_task_transfer.items():
            if task_type in target_types and source_type != task_type:
                for snippets in self._knowledge_base.values():
                    for s in snippets:
                        if s["source_type"] == source_type:
                            candidate = dict(s)
                            candidate["transfer_from"] = source_type
                            candidate["confidence"] *= 0.85  # discount transferred knowledge
                            candidates.append(candidate)

        # Sort by confidence, return top_k
        candidates.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return candidates[:top_k]

    def apply_knowledge(self, task: str, task_type: str, reasoning_step: str) -> str:
        """Apply relevant knowledge snippets to augment a reasoning step.

        Returns the reasoning step with knowledge-augmented hints appended.
        """
        snippets = self.get_relevant_knowledge(task_type, task, top_k=3)
        if not snippets:
            return reasoning_step

        hints = []
        for s in snippets:
            hints.append(f"[{s['category']}] {s['principle']}")

        return reasoning_step + "\n\n--- Internalized Knowledge ---\n" + "\n".join(hints)

    def get_stats(self) -> dict:
        """Return knowledge internalization statistics."""
        return {
            "total_internalized": self._total_internalized,
            "knowledge_categories": list(self._knowledge_base.keys()),
            "cross_task_transfers": {k: list(v) for k, v in self._cross_task_transfer.items()},
        }


class ReflectiveSampler:
    """Reflection-Enhanced Reasoning Sampling (RERS).

    Tracks failure clusters, scores them by priority, and generates
    structured reflective examples for adaptive sampling.

    Includes:
      - DualLevelCurriculumRL: micro (per-step) and macro (cross-trajectory) difficulty
      - KnowledgeInternalization: distill failure lessons into reusable snippets
    """

    def __init__(self, decay_factor: float = 0.9, top_k_clusters: int = 10):
        self._clusters: dict[str, FailureCluster] = {}
        self._samples: list[dict] = []
        self._total_paths = 0
        self._decay_factor = decay_factor
        self._top_k_clusters = top_k_clusters
        # NEW: Dual-level curriculum RL
        self._curriculum = DualLevelCurriculumRL()
        # NEW: Knowledge internalization
        self._knowledge = KnowledgeInternalization()
        # Curriculum stage tracking
        self._curriculum_stage = 0

    # ── Public API ─────────────────────────────────────────────��

    def reflect_on_failure(self, path: dict) -> dict:
        """Analyze a single failure path, extract structured reflection.

        Args:
            path: Dict with at least 'task' and 'error' keys.

        Returns:
            Dict with task info, error cluster, reflections, and lessons.
        """
        task = path.get("task", "")
        error = path.get("error", "")
        task_type = _task_type(task)
        signature = _error_signature(str(error))

        # Update the cluster
        if signature not in self._clusters:
            self._clusters[signature] = FailureCluster(signature, task_type)
        self._clusters[signature].add_failure(path)

        # Update dual-level curriculum RL
        self._curriculum.update_task_difficulty(task_type, task, str(error))
        self._curriculum.register_step(task_type, {
            "content": task,
            "error": error,
            "intermediate_steps": path.get("steps_taken", path.get("n_steps", 0)),
        })

        # Generate reflection for this single failure
        reflections = self._generate_reflections(task, str(error), task_type)
        lesson_count = len(reflections)

        result = {
            "task": task[:200],
            "error": str(error)[:200],
            "signature": signature,
            "task_type": task_type,
            "reflections": reflections,
            "lessons": lesson_count,
            "cluster_size": self._clusters[signature].total_count,
            "priority": round(self._clusters[signature].priority_score, 4),
        }
        self._samples.append(result)
        self._total_paths += 1
        return result

    def sample_reflective(self, failure_paths: list[dict]) -> list[str]:
        """Sample reflective lessons from failure paths using adaptive weights.

        Uses priority-weighted sampling: failure clusters with higher
        priority scores are more likely to contribute.

        Args:
            failure_paths: List of failure path dicts.

        Returns:
            List of unique reflection strings, weighted by cluster priority.
        """
        if not failure_paths:
            return []

        # Process all failures (updates clusters)
        all_reflections: list[str] = []
        for fp in failure_paths:
            result = self.reflect_on_failure(fp)
            all_reflections.extend(result["reflections"])

        # Build priority-weighted cluster summaries
        sorted_clusters = sorted(
            self._clusters.values(),
            key=lambda c: c.priority_score,
            reverse=True,
        )

        # Generate structured reflective examples from top clusters
        structured_examples: list[str] = []
        for cluster in sorted_clusters[:self._top_k_clusters]:
            example = cluster.generate_reflective_example(max_examples=2)
            for lesson in example["lessons"]:
                structured_examples.append(
                    f"[{example['task_type']}|freq={example['frequency']}] "
                    f"{lesson}"
                )
            # NEW: Internalize knowledge from this cluster
            self._knowledge.internalize(cluster)

        # Apply internalized knowledge to refine reflections
        for fp in failure_paths:
            task_type = _task_type(fp.get("task", ""))
            knowledge_augmented = self._knowledge.apply_knowledge(
                fp.get("task", ""), task_type, ""
            )
            if knowledge_augmented and "--- Internalized Knowledge ---" in knowledge_augmented:
                for line in knowledge_augmented.split("\n"):
                    if line.startswith("[") and "]" in line:
                        structured_examples.append(f"[knowledge] {line}")
                        break

        # Combine unique reflections with structured examples
        unique_reflections = list(set(all_reflections))
        unique_reflections.extend(structured_examples)

        # Deduplicate again after merging
        seen: set[str] = set()
        result: list[str] = []
        for r in unique_reflections:
            if r not in seen:
                seen.add(r)
                result.append(r)

        return result

    # ── Internal helpers ────────────────────────────────────────

    @staticmethod
    def _generate_reflections(task: str, error: str, task_type: str) -> list[str]:
        """Generate structured reflection strings from a single failure."""
        reflections: list[str] = []
        error_lower = str(error).lower()

        if "timeout" in error_lower:
            reflections.append(
                "Efficiency: task exceeded time limit — attempt sub-goal decomposition"
            )
        if "invalid" in error_lower or "error" in error_lower:
            reflections.append(
                "Validation: output was invalid — add structural checks before returning"
            )
        if not task and not error:
            reflections.append("Input: empty task or error — verify input pipeline")
        if task_type == "code_generation":
            reflections.append("Code: ensure implementation is testable incrementally")
        elif task_type == "reasoning":
            reflections.append("Reasoning: verify intermediate deductions explicitly")
        elif task_type == "planning":
            reflections.append("Planning: consider alternative decomposition strategies")

        if not reflections:
            reflections.append(f"Unknown-failure [{str(error)[:60]}] — log for manual review")
        return reflections

    def get_cluster_summary(self) -> list[dict]:
        """Return a summary of all tracked failure clusters."""
        return [
            {
                "signature": c.signature,
                "task_type": c.task_type,
                "count": c.total_count,
                "priority": round(c.priority_score, 4),
            }
            for c in sorted(
                self._clusters.values(),
                key=lambda c: c.priority_score,
                reverse=True,
            )
        ]

    def get_stats(self) -> dict:
        """Return sampling statistics."""
        unique_clusters = len(self._clusters)
        total_in_clusters = sum(c.total_count for c in self._clusters.values())
        top_cluster = max(self._clusters.values(), key=lambda c: c.priority_score) \
            if self._clusters else None

        # Count unique reflections across all samples
        all_reflections: list[str] = []
        for s in self._samples:
            all_reflections.extend(s.get("reflections", []))
        unique_refs = len(set(all_reflections))

        return {
            "total_paths": self._total_paths,
            "unique_clusters": unique_clusters,
            "total_in_clusters": total_in_clusters,
            "unique_reflections": unique_refs,
            "top_cluster": top_cluster.signature if top_cluster else None,
            "top_priority": round(top_cluster.priority_score, 4) if top_cluster else 0.0,
            "curriculum_stage": self._curriculum_stage,
            "curriculum": self._curriculum.curriculum_schedule(),
            "knowledge_internalized": self._knowledge.get_stats(),
        }
