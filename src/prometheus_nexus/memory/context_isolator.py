"""ContextIsolator — Sub-agent context isolation.

Based on:
- "How We Built Our Multi-Agent Research System" (Anthropic, 2025)
  "Subagents facilitate compression by operating in parallel with their own context windows."
- Claude Code: "Sub-agents only do investigation, never modify code"

Key Concepts:
    1. Each sub-agent gets an isolated context snapshot
    2. Sub-agent operates independently within its context
    3. Results are compressed before returning to parent
    4. Prevents investigation noise from contaminating main agent

Algorithm:
    isolate(parent_context, task):
        1. Snapshot relevant portion of parent context
        2. Create isolated context with only task-relevant info
        3. Execute task in isolation
        4. Compress results before returning

    merge(parent_context, sub_result):
        1. Extract key findings from sub_result
        2. Append to parent context with isolation marker
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from dataclasses import dataclass, field


@dataclass
class IsolatedContext:
    """An isolated context window for a sub-agent."""
    context_id: str = ""
    task: str = ""
    snapshot: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    created_at: float = 0.0
    completed: bool = False


@dataclass
class IsolationResult:
    """Result of isolated execution."""
    context_id: str = ""
    task: str = ""
    findings: list[str] = field(default_factory=list)
    compressed_summary: str = ""
    tokens_used: int = 0
    duration_ms: float = 0.0


class ContextIsolator:
    """Sub-agent context isolation.

    Based on Anthropic's Multi-Agent Research System (2025).

    Usage:
        isolator = ContextIsolator(max_snapshot_tokens=5000)

        # Create isolated context for sub-agent
        snapshot = isolator.create_snapshot(
            parent_context=["Previous discussion about AI...", "User asked about safety..."],
            task="Research AI safety regulations",
        )

        # Sub-agent works in isolation
        findings = ["EU AI Act passed in 2024", "NIST framework published"]

        # Merge compressed results back
        result = isolator.merge(snapshot, findings)
        print(result.compressed_summary)
    """

    def __init__(self, max_snapshot_tokens: int = 5000,
                 max_findings: int = 10):
        self._max_snapshot = max_snapshot_tokens
        self._max_findings = max_findings
        self._isolations: list[dict] = []
        self._total_tokens_saved = 0

    def create_snapshot(self, parent_context: list[str], task: str) -> IsolatedContext:
        relevant = self._select_relevant(parent_context, task)

        token_estimate = sum(len(s.split()) * 1.3 for s in relevant)
        while token_estimate > self._max_snapshot and len(relevant) > 1:
            removed = relevant.pop(0)
            token_estimate -= len(removed.split()) * 1.3

        context_id = f"iso_{int(time.time() * 1000)}"
        snapshot = IsolatedContext(
            context_id=context_id,
            task=task,
            snapshot=relevant,
            created_at=time.time(),
        )

        self._isolations.append({"id": context_id, "task": task, "snapshot_size": len(relevant)})
        return snapshot

    def merge(self, context: IsolatedContext, findings: list[str]) -> IsolationResult:
        start = time.time()
        context.findings = findings
        context.completed = True

        compressed = self._compress_findings(findings)

        parent_tokens = sum(len(s.split()) for s in context.snapshot)
        compressed_tokens = len(compressed.split())
        tokens_saved = parent_tokens + sum(len(f.split()) for f in findings) - compressed_tokens
        self._total_tokens_saved += max(0, tokens_saved)

        return IsolationResult(
            context_id=context.context_id,
            task=context.task,
            findings=findings,
            compressed_summary=compressed,
            tokens_used=compressed_tokens,
            duration_ms=(time.time() - start) * 1000,
        )

    def _select_relevant(self, context: list[str], task: str) -> list[str]:
        task_words = set(task.lower().split())
        scored = []
        for item in context:
            item_words = set(item.lower().split())
            overlap = len(task_words & item_words)
            scored.append((overlap, item))
        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:5]]

    def _compress_findings(self, findings: list[str]) -> str:
        if not findings:
            return ""
        if len(findings) <= 3:
            return "; ".join(findings)
        top = findings[:self._max_findings]
        compressed = f"Key findings ({len(top)} items): " + "; ".join(
            f"{i+1}. {f[:80]}" for i, f in enumerate(top)
        )
        if len(findings) > self._max_findings:
            compressed += f" (+{len(findings) - self._max_findings} more)"
        return compressed

    def get_stats(self) -> dict:
        return {
            "total_isolations": len(self._isolations),
            "tokens_saved": self._total_tokens_saved,
            "avg_snapshot_size": sum(i["snapshot_size"] for i in self._isolations) / max(len(self._isolations), 1),
        }
