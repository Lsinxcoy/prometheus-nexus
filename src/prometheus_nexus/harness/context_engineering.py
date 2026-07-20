"""ContextEngineering — Unified orchestration of Write/Select/Compress/Isolate.

Based on:
- "Context Engineering for Agents" (LangChain, 2025)
- "Don't Build Multi-Agents" (Cognition, 2025): "Context engineering is the #1 job"
- "How We Built Our Multi-Agent Research System" (Anthropic, 2025)
- "How Long Contexts Fail" (Breunig, 2025)
- Andrej Karpathy: "Context engineering is the delicate art and science of filling
  the context window with just the right information for the next step"

Four Strategies:
    1. Write: Save context to external storage (scratchpad, memory)
    2. Select: Retrieve relevant context from storage
    3. Compress: Reduce context size while preserving key information
    4. Isolate: Separate context for parallel sub-agent execution

Context Types:
    - Instructions: System prompts, rules, tool descriptions
    - Knowledge: Facts, memories, retrieved information
    - Tools: Tool descriptions, call results

Algorithm:
    manage_context(task, history):
        1. Write: snapshot current state to external storage
        2. Select: retrieve relevant memories/knowledge
        3. Compress: reduce history if too long
        4. Isolate: create sub-contexts for parallel tasks
        5. Assemble final context for next step

Complexity:
    manage(): O(S + R + C) where S=selection, R=retrieval, C=compression
"""
from __future__ import annotations



import logging

import re
import time
from dataclasses import dataclass, field
from typing import Any
logger = logging.getLogger(__name__)


@dataclass
class ContextComponent:
    """A component of the context window."""
    name: str = ""
    type: str = ""  # instruction, knowledge, tool, history
    content: str = ""
    priority: int = 5  # 1=highest, 10=lowest
    tokens: int = 0
    timestamp: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class ContextSnapshot:
    """A snapshot of context state for Write strategy."""
    snapshot_id: str = ""
    task: str = ""
    components: list[ContextComponent] = field(default_factory=list)
    total_tokens: int = 0
    timestamp: float = 0.0


@dataclass
class ContextResult:
    """Result of context engineering."""
    components: list[ContextComponent] = field(default_factory=list)
    total_tokens: int = 0
    write_saved: int = 0
    select_retrieved: int = 0
    compressed_tokens: int = 0
    isolated_contexts: int = 0
    strategy_used: str = ""


class ContextEngineering:
    """Unified orchestration of Write/Select/Compress/Isolate.

    Based on Context Engineering research (LangChain, Anthropic, Cognition 2025).

    Usage:
        ce = ContextEngineering(max_tokens=128000)

        # Write: save context externally
        snapshot = ce.write(task="answer question", components=[
            ContextComponent(name="system", type="instruction", content="Be helpful"),
            ContextComponent(name="history", type="history", content="Previous Q&A"),
        ])

        # Select: retrieve relevant context
        selected = ce.select(query="AI safety", storage=memory_store, limit=5)

        # Compress: reduce context size
        compressed = ce.compress(context_components, target_ratio=0.5)

        # Isolate: create sub-contexts
        isolated = ce.isolate(parent_context, sub_task="research topic")

        # Full pipeline
        result = ce.manage_context(task, history, memory_store)
    """

    def __init__(self, max_tokens: int = 128000):
        self._max_tokens = max_tokens
        self._snapshots: list[ContextSnapshot] = []
        self._stats = {
            "writes": 0, "selects": 0, "compressions": 0, "isolations": 0,
            "total_tokens_saved": 0, "total_components": 0,
        }

    def write(self, task: str, components: list[ContextComponent]) -> ContextSnapshot:
        """Write: Save context to external storage for later retrieval.

        From LangChain: "Scratchpad (temporary notes), Memory (cross-session storage)"
        From Anthropic: "LeadResearcher writes plan to Memory to prevent truncation loss"

        Args:
            task: Current task description.
            components: Context components to save.

        Returns:
            ContextSnapshot with saved state.
        """
        total_tokens = sum(c.tokens for c in components)
        snapshot = ContextSnapshot(
            snapshot_id=f"snap_{int(time.time() * 1000)}",
            task=task,
            components=components,
            total_tokens=total_tokens,
            timestamp=time.time(),
        )
        self._snapshots.append(snapshot)
        self._stats["writes"] += 1
        return snapshot

    def select(self, query: str, storage: Any = None, limit: int = 5) -> list[ContextComponent]:
        """Select: Retrieve relevant context from external storage.

        From Karpathy: "filling the context window with just the right information"
        From Anthropic: "CLAUDE.md as programmatic memory automatically injected"

        Args:
            query: Search query for retrieval.
            storage: External storage (memory store, knowledge base).
            limit: Maximum components to retrieve.

        Returns:
            List of retrieved ContextComponents.
        """
        results = []

        # Try to retrieve from memory store if available
        if storage and hasattr(storage, 'recall'):
            try:
                recall_results = storage.recall(query, limit=limit)
                for r in recall_results.hits:
                    results.append(ContextComponent(
                        name=f"memory_{r.node_id[:8]}",
                        type="knowledge",
                        content=r.content,
                        priority=3,
                        tokens=len(r.content.split()) * 2,
                        metadata={"source": "memory", "score": r.score},
                    ))
            except Exception as e:
                logger.warning("ContextEngineering memory recall failed: %s", e)

        # Try to retrieve from graph memory if available
        if storage and hasattr(storage, 'search'):
            try:
                graph_results = storage.search(query, limit=limit)
                for r in graph_results:
                    content = r.content if hasattr(r, 'content') else str(r)
                    results.append(ContextComponent(
                        name=f"graph_{hash(content) % 10000}",
                        type="knowledge",
                        content=content[:500],
                        priority=4,
                        tokens=len(content.split()) * 2,
                        metadata={"source": "graph"},
                    ))
            except Exception as e:
                logger.warning("ContextEngineering graph search failed: %s", e)

        # Sort by priority and limit
        results.sort(key=lambda c: c.priority)
        results = results[:limit]

        self._stats["selects"] += 1
        self._stats["total_components"] += len(results)
        return results

    def compress(self, components: list[ContextComponent],
                 target_ratio: float = 0.5) -> list[ContextComponent]:
        """Compress: Reduce context size while preserving key information.

        From Cognition: "Compression is the #1 job of engineers building AI agents"
        From Anthropic: "Subagents facilitate compression by operating in parallel"

        Args:
            components: Components to compress.
            target_ratio: Target compression ratio (0.5 = keep 50%).

        Returns:
            Compressed list of components.
        """
        if not components:
            return []

        total_tokens = sum(c.tokens for c in components)
        target_tokens = int(total_tokens * target_ratio)

        if total_tokens <= target_tokens:
            return components

        # Sort by priority (lower = more important)
        sorted_components = sorted(components, key=lambda c: c.priority)

        # Keep high-priority components, compress low-priority ones
        kept = []
        kept_tokens = 0

        for comp in sorted_components:
            if kept_tokens + comp.tokens <= target_tokens:
                kept.append(comp)
                kept_tokens += comp.tokens
            else:
                # Compress this component
                compressed_content = self._compress_text(comp.content, target_ratio)
                compressed_tokens = len(compressed_content.split()) * 2
                if kept_tokens + compressed_tokens <= target_tokens:
                    kept.append(ContextComponent(
                        name=comp.name,
                        type=comp.type,
                        content=compressed_content,
                        priority=comp.priority,
                        tokens=compressed_tokens,
                        timestamp=comp.timestamp,
                        metadata={**comp.metadata, "compressed": True},
                    ))
                    kept_tokens += compressed_tokens

        saved = total_tokens - kept_tokens
        self._stats["compressions"] += 1
        self._stats["total_tokens_saved"] += saved

        return kept

    @staticmethod
    def _compress_text(text: str, target_ratio: float = 0.5) -> str:
        """Truncate text to approximately target_ratio of original length."""
        if not text:
            return text
        max_chars = max(10, int(len(text) * target_ratio))
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "..."

    def isolate(self,
                parent_components,
                sub_task: str, max_tokens: int = 32000) -> tuple[list[ContextComponent], list[ContextComponent]]:
        """Isolate: Create separate context for sub-agent execution.

        From Anthropic: "Subagents facilitate compression by operating in
        parallel with their own context windows"
        From Claude Code: "Sub-agents only do investigation, never modify code"

        Args:
            parent_components: Parent context components.
            sub_task: Description of sub-task for isolation.
            max_tokens: Maximum tokens for isolated context.

        Returns:
            Tuple of (isolated_context, remaining_parent_context).
        """
        # Select relevant components for isolation
        isolated = []
        remaining = []

        task_words = set(sub_task.lower().split())

        for comp in parent_components:
            relevance = self._compute_relevance(comp.content, task_words)
            if relevance > 0.3:
                isolated.append(comp)
            else:
                remaining.append(comp)

        # Ensure isolated context fits within budget
        total_tokens = sum(c.tokens for c in isolated)
        if total_tokens > max_tokens:
            isolated.sort(key=lambda c: c.priority)
            kept = []
            kept_tokens = 0
            for comp in isolated:
                if kept_tokens + comp.tokens <= max_tokens:
                    kept.append(comp)
                    kept_tokens += comp.tokens
                else:
                    remaining.append(comp)
            isolated = kept

        self._stats["isolations"] += 1
        return isolated, remaining

    def manage_context(self, task: str, history: list[str],
                       memory_store: Any = None,
                       max_tokens: int = 128000) -> ContextResult:
        """Full context engineering pipeline.

        Orchestrates Write → Select → Compress → Isolate for optimal context.

        Args:
            task: Current task description.
            history: Conversation history.
            memory_store: External memory store.
            max_tokens: Maximum context window size.

        Returns:
            ContextResult with assembled components and metrics.
        """
        components = []

        # 1. Write: snapshot current state
        history_content = "\n".join(history[-10:])  # Keep last 10 turns
        history_tokens = len(history_content.split()) * 2

        # 2. Select: retrieve relevant context from memory
        if memory_store:
            selected = self.select(task, memory_store, limit=5)
            components.extend(selected)

        # 3. Add history as component
        if history_content:
            components.append(ContextComponent(
                name="history",
                type="history",
                content=history_content,
                priority=2,
                tokens=history_tokens,
            ))

        # 4. Add task as component
        components.append(ContextComponent(
            name="task",
            type="instruction",
            content=task,
            priority=1,
            tokens=len(task.split()) * 2,
        ))

        # 5. Compress if over budget
        total_tokens = sum(c.tokens for c in components)
        compressed_tokens = 0
        if total_tokens > max_tokens:
            before = total_tokens
            components = self.compress(components, target_ratio=max_tokens / total_tokens)
            compressed_tokens = before - sum(c.tokens for c in components)

        # 6. Write snapshot for future retrieval
        self.write(task, components)

        final_tokens = sum(c.tokens for c in components)

        return ContextResult(
            components=components,
            total_tokens=final_tokens,
            select_retrieved=len([c for c in components if c.metadata.get("source")]),
            compressed_tokens=compressed_tokens,
            strategy_used="write_select_compress",
        )

    def _compute_relevance(self, content: str, query_words: set) -> float:
        """Compute relevance score between content and query."""
        if not content or not query_words:
            return 0.0
        content_words = set(content.lower().split())
        overlap = query_words & content_words
        return len(overlap) / max(len(query_words), 1)

    def skip(self, content: str, relevance_threshold: float = 0.3) -> bool:
        """Skip: 判断是否应跳过一段内容（完全不注入上下文）。

        Args:
            content: 待判断的内容。
            relevance_threshold: 相关性阈值。

        Returns:
            True 表示应跳过，False 表示应保留。
        """
        if not content:
            return True
        return len(content.split()) < 3

    def rollback(self, components: list[ContextComponent],
                 checkpoint_id: str = None) -> list[ContextComponent]:
        """Rollback: 回退到上一个检查点。

        从 _snapshots 中找回 check_point，恢复到那时状态。

        Args:
            components: 当前上下文组件列表。
            checkpoint_id: 检查点 ID（若为 None，回退到最后一次 snapshot）。

        Returns:
            回退后的 context components。
        """
        if checkpoint_id:
            target = [s for s in self._snapshots if hasattr(s, 'id') and s.id == checkpoint_id]
        else:
            target = self._snapshots[-1:] if self._snapshots else []

        if target:
            self._stats["rollbacks"] = self._stats.get("rollbacks", 0) + 1
            return list(target[0].components)
        logger.debug("ContextEngine rollback: checkpoint not found (id=%s)", checkpoint_id)
        return components

    def delete(self, components: list[ContextComponent],
               name_filter: str = None) -> list[ContextComponent]:
        """Delete: 从上下文中删除指定组件。

        Args:
            components: 当前上下文组件列表。
            name_filter: 要删除的组件名称（若 None，不删除）。

        Returns:
            删除后的 context components。
        """
        if name_filter is None:
            return components
        result = [c for c in components if c.name != name_filter]
        if len(result) < len(components):
            self._stats["deletions"] = self._stats.get("deletions", 0) + (len(components) - len(result))
        return result

    def localized_correction(self, query: str, error_context: str,
                              examples: list[dict] | None = None,
                              max_chars: int = 2000) -> str | None:
        """L-ICL: Localized In-Context Learning for planners (arXiv 2602.00276).

        Iteratively augments instructions with *minimal* ICL examples.
        Key insight from the paper: 2000-char targeted correction beats
        20000-char full trajectory retrieval for planner tasks.

        Unlike the Write/Select/Compress/Isolate framework above (which
        is general-purpose context engineering), this method implements
        the paper's specific L-ICL algorithm:
          1. Classify the query → planner domain
          2. Extract the failure pattern from error_context
          3. Generate 1-3 minimal ICL examples targeting that pattern
          4. Assemble a compact correction string (≤ max_chars)

        Args:
            query: The original query that failed.
            error_context: Description of the error/failure context.
            examples: Optional list of prior ICL examples for this planner.
                      Each example dict: {"query": str, "correct_action": str}
            max_chars: Maximum correction text length (default 2000, per paper).

        Returns:
            A localized correction instruction string, or None if no correction
            is applicable (empty query or error).
        """
        if not query or not error_context:
            return None

        # 1. Classify the planner domain
        domain = self._classify_planner_domain(query)

        # 2. Extract failure pattern from error
        failure_pattern = self._extract_failure_pattern(error_context)

        # 3. Generate 1-3 minimal ICL examples
        icl_examples = self._generate_l_icl_examples(
            query, failure_pattern, domain, examples or []
        )

        # 4. Assemble correction with optional prior examples merged
        correction_lines = [
            f"[L-ICL Correction — arXiv 2602.00276]",
            f"Domain: {domain}",
            f"Failure pattern: {failure_pattern}",
            "",
            "Targeted ICL examples:",
        ]

        for i, ex in enumerate(icl_examples):
            correction_lines.append(f"  Example {i + 1}:")
            correction_lines.append(f"    Query: {ex.get('query', '')[:150]}")
            correction_lines.append(f"    Correct action: {ex.get('correct_action', '')[:200]}")

        correction_lines.append("")
        correction_lines.append(f"Instruction augmentation: When planning for [{domain}], "
                                f"avoid [{failure_pattern}]. Instead apply the {len(icl_examples)} "
                                f"corrective example(s) above as guardrails.")

        correction = "\n".join(correction_lines)

        if len(correction) > max_chars:
            # Truncate from the middle: keep header and last example
            header_len = len(
                f"[L-ICL Correction — arXiv 2602.00276]\n"
                f"Domain: {domain}\n"
                f"Failure pattern: {failure_pattern}\n\n"
            )
            tail = f"\n\nInstruction augmentation: When planning for [{domain}], avoid [{failure_pattern}]."
            remaining = max_chars - header_len - len(tail)
            if remaining > 100:
                middle = "\n".join(correction_lines[4:-2])
                if len(middle) > remaining:
                    middle = middle[: remaining - 20] + "\n  ...(truncated)..."
                correction = (
                    correction_lines[0] + "\n" +
                    correction_lines[1] + "\n" +
                    correction_lines[2] + "\n\n" +
                    middle + "\n" +
                    tail
                )
            else:
                correction = correction[:max_chars]

        # Track stats
        self._stats["localized_corrections"] = self._stats.get("localized_corrections", 0) + 1
        self._stats["l_icl_examples_generated"] = (
            self._stats.get("l_icl_examples_generated", 0) + len(icl_examples)
        )

        return correction

    @staticmethod
    def _classify_planner_domain(query: str) -> str:
        """Classify a planner query into a domain for L-ICL targeting."""
        q = query.lower()
        if any(w in q for w in ["code", "program", "implement", "script", "function"]):
            return "code_generation"
        if any(w in q for w in ["schedule", "timetable", "calendar", "deadline"]):
            return "scheduling"
        if any(w in q for w in ["route", "path", "trajectory", "map"]):
            return "path_planning"
        if any(w in q for w in ["resource", "budget", "allocate", "assign"]):
            return "resource_allocation"
        if any(w in q for w in ["research", "investigate", "search", "find"]):
            return "research_planning"
        if any(w in q for w in ["decompose", "break down", "subtask", "phase"]):
            return "task_decomposition"
        if any(w in q for w in ["verify", "validate", "test", "check"]):
            return "verification"
        if any(w in q for w in ["learn", "study", "curriculum", "teach"]):
            return "learning_planning"
        return "general_planning"

    @staticmethod
    def _extract_failure_pattern(error_context: str) -> str:
        """Extract a compact failure pattern from error context."""
        ec = error_context.lower()
        if "timeout" in ec or "too slow" in ec or "timed out" in ec:
            return "horizon_overrun"
        if "invalid" in ec or "malformed" in ec or "syntax" in ec:
            return "invalid_output_format"
        if "missing" in ec or "not found" in ec or "nonexistent" in ec:
            return "missing_prerequisite"
        if "cycle" in ec or "circular" in ec or "infinite" in ec:
            return "circular_dependency"
        if "conflict" in ec or "contradict" in ec or "inconsistent" in ec:
            return "plan_conflict"
        if "incomplete" in ec or "partial" in ec or "insufficient" in ec:
            return "incomplete_coverage"
        if "redundant" in ec or "duplicate" in ec or "repetitive" in ec:
            return "redundant_steps"
        return "general_planning_error"

    def _generate_l_icl_examples(
        self,
        query: str,
        failure_pattern: str,
        domain: str,
        prior_examples: list[dict],
    ) -> list[dict]:
        """Generate 1-3 minimal ICL examples targeting the failure pattern.

        Produces counter-example + correct-action pairs that a planner
        can use as localized instruction augmentation. Merges with any
        prior examples for the same domain/pattern.

        Args:
            query: The original query.
            failure_pattern: Extracted failure pattern string.
            domain: Planner domain classification.
            prior_examples: Previously stored ICL examples.

        Returns:
            List of dicts with 'query' and 'correct_action' keys.
        """
        examples: list[dict] = []

        # Include matching prior examples first (up to 2)
        matched_prior = [
            ex for ex in prior_examples
            if ex.get("_domain") == domain and ex.get("_pattern") == failure_pattern
        ]
        for ex in matched_prior[:2]:
            examples.append({
                "query": ex.get("query", query)[:150],
                "correct_action": ex.get("correct_action", "Review and adjust plan")[:200],
            })

        # Generate fresh examples based on pattern
        pattern_examples = {
            "horizon_overrun": [
                {
                    "query": f"Plan execution for {domain} task {' '.join(query.split()[:8])}",
                    "correct_action": "Decompose into subtasks with per-subtask time budgets. "
                                      "Use iterative deepening: execute the first subtask, check progress, then expand.",
                },
                {
                    "query": f"Long-horizon {domain} plan with many steps",
                    "correct_action": "Set intermediate milestones with checkpoint validation. "
                                      "If a milestone is missed, replan the remaining horizon.",
                },
            ],
            "invalid_output_format": [
                {
                    "query": f"Produce structured output for {domain}",
                    "correct_action": "Define output schema before execution. Validate each field "
                                      "against the schema after every step. Reject malformed intermediate results.",
                },
            ],
            "missing_prerequisite": [
                {
                    "query": f"{domain} plan with dependencies",
                    "correct_action": "Run a prerequisite scan before planning. "
                                      "Mark unresolved dependencies as blockers. "
                                      "Generate alternative paths when a dependency is unsatisfied.",
                },
            ],
            "circular_dependency": [
                {
                    "query": f"Interdependent steps in {domain}",
                    "correct_action": "Topologically sort all steps. Detect cycles with DFS. "
                                      "If a cycle exists, consolidate the involved steps into a single meta-step.",
                },
            ],
            "plan_conflict": [
                {
                    "query": f"Avoiding conflicts in {domain} plan",
                    "correct_action": "Run pairwise conflict detection across all plan steps. "
                                      "For each conflict, apply a precedence constraint or merge the conflicting steps.",
                },
            ],
            "incomplete_coverage": [
                {
                    "query": f"Full coverage plan for {domain}",
                    "correct_action": "List all required sub-goals explicitly. "
                                      "Cross-check each against the original objective. "
                                      "Flag uncovered objectives for additional step generation.",
                },
            ],
            "redundant_steps": [
                {
                    "query": f"Optimizing {domain} plan",
                    "correct_action": "Deduplicate steps with identical preconditions and effects. "
                                      "Merge adjacent steps that can be combined. "
                                      "Remove steps that do not contribute to any sub-goal.",
                },
            ],
            "general_planning_error": [
                {
                    "query": f"General {domain} planning",
                    "correct_action": "Analyze the failed attempt. Identify the earliest step where "
                                      "the plan diverged from expectations. Generate a revised prefix "
                                      "from that point forward.",
                },
            ],
        }

        fresh = pattern_examples.get(failure_pattern, pattern_examples["general_planning_error"])
        needed = min(3 - len(examples), len(fresh))
        for ex in fresh[:needed]:
            examples.append({
                "query": ex["query"][:150],
                "correct_action": ex["correct_action"][:200],
            })

        return examples[:3]

    def get_stats(self) -> dict:
        return dict(self._stats)
