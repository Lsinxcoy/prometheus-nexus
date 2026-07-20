"""PlanWriter — Detailed implementation plan generation.

Based on: obra/superpowers writing-plans skill
Key insight: Break work into 2-5 minute tasks with exact file paths and verification steps.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from dataclasses import dataclass, field


@dataclass
class PlanTask:
    task_id: str = ""
    description: str = ""
    file_paths: list[str] = field(default_factory=list)
    verification_steps: list[str] = field(default_factory=list)
    estimated_minutes: int = 3
    dependencies: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, in_progress, complete


@dataclass
class ImplementationPlan:
    feature: str = ""
    tasks: list[PlanTask] = field(default_factory=list)
    total_estimated_minutes: int = 0
    task_count: int = 0
    ready_to_execute: bool = False


class PlanWriter:
    """Detailed implementation plan generator.

    Based on Superpowers writing-plans skill:
    1. Break work into bite-sized tasks (2-5 minutes each)
    2. Each task has exact file paths
    3. Each task has verification steps
    4. Tasks are ordered by dependency
    """

    def __init__(self):
        self._history: list[dict] = []
        self._plans: list[ImplementationPlan] = []

    def write_plan(self, feature: str, context: str = "",
                   max_tasks: int = 10) -> ImplementationPlan:
        result = ImplementationPlan(feature=feature)

        tasks = self._generate_tasks(feature, context)
        result.tasks = tasks[:max_tasks]
        result.task_count = len(result.tasks)
        result.total_estimated_minutes = sum(t.estimated_minutes for t in result.tasks)
        result.ready_to_execute = result.task_count > 0

        self._history.append({
            "feature": feature,
            "tasks": result.task_count,
            "estimated_minutes": result.total_estimated_minutes,
        })
        self._plans.append(result)

        return result

    def _generate_tasks(self, feature: str, context: str) -> list[PlanTask]:
        tasks = []
        feature_lower = feature.lower()

        if "fix" in feature_lower or "bug" in feature_lower:
            tasks.append(PlanTask(
                task_id="task_1",
                description="Write a failing test that reproduces the bug",
                verification_steps=["Test fails without fix", "Test captures exact symptom"],
                estimated_minutes=3,
            ))
            tasks.append(PlanTask(
                task_id="task_2",
                description="Implement minimal fix",
                file_paths=["src/prometheus_nexus/"],
                verification_steps=["All existing tests pass", "New test passes"],
                estimated_minutes=5,
                dependencies=["task_1"],
            ))
            tasks.append(PlanTask(
                task_id="task_3",
                description="Add regression test",
                verification_steps=["Regression test prevents recurrence"],
                estimated_minutes=2,
                dependencies=["task_2"],
            ))

        elif "add" in feature_lower or "create" in feature_lower or "implement" in feature_lower:
            tasks.append(PlanTask(
                task_id="task_1",
                description="Design the interface and data structures",
                verification_steps=["Interface is clear", "Data structures are minimal"],
                estimated_minutes=3,
            ))
            tasks.append(PlanTask(
                task_id="task_2",
                description="Write tests for the new functionality",
                verification_steps=["Tests cover main paths", "Tests cover edge cases"],
                estimated_minutes=5,
                dependencies=["task_1"],
            ))
            tasks.append(PlanTask(
                task_id="task_3",
                description="Implement core logic",
                file_paths=["src/prometheus_nexus/"],
                verification_steps=["All tests pass", "No regressions"],
                estimated_minutes=5,
                dependencies=["task_2"],
            ))
            tasks.append(PlanTask(
                task_id="task_4",
                description="Integrate with existing pipeline",
                verification_steps=["Integration tests pass", "Performance acceptable"],
                estimated_minutes=3,
                dependencies=["task_3"],
            ))

        elif "improve" in feature_lower or "optimize" in feature_lower:
            tasks.append(PlanTask(
                task_id="task_1",
                description="Measure current baseline performance",
                verification_steps=["Baseline recorded", "Metrics defined"],
                estimated_minutes=3,
            ))
            tasks.append(PlanTask(
                task_id="task_2",
                description="Identify optimization target",
                verification_steps=["Target identified", "Expected improvement estimated"],
                estimated_minutes=2,
                dependencies=["task_1"],
            ))
            tasks.append(PlanTask(
                task_id="task_3",
                description="Implement optimization",
                file_paths=["src/prometheus_nexus/"],
                verification_steps=["Optimization applied", "No regressions"],
                estimated_minutes=5,
                dependencies=["task_2"],
            ))
            tasks.append(PlanTask(
                task_id="task_4",
                description="Verify improvement meets target",
                verification_steps=["Performance improved", "Within acceptable range"],
                estimated_minutes=2,
                dependencies=["task_3"],
            ))

        else:
            tasks.append(PlanTask(
                task_id="task_1",
                description="Analyze requirements and constraints",
                verification_steps=["Requirements documented", "Constraints identified"],
                estimated_minutes=3,
            ))
            tasks.append(PlanTask(
                task_id="task_2",
                description="Design solution approach",
                verification_steps=["Approach is sound", "Complexity is acceptable"],
                estimated_minutes=3,
                dependencies=["task_1"],
            ))
            tasks.append(PlanTask(
                task_id="task_3",
                description="Implement and test",
                verification_steps=["Implementation complete", "Tests pass"],
                estimated_minutes=5,
                dependencies=["task_2"],
            ))

        return tasks

    def get_stats(self) -> dict:
        return {"plans": len(self._history), "total_tasks": sum(p["tasks"] for p in self._history)}
