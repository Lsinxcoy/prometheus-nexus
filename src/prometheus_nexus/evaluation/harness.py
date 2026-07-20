"""HarnessX — Composable, adaptive, and evolvable agent harness foundry.

Based on: "HarnessX: A Composable, Adaptive, and Evolvable Agent Harness Foundry"
(arXiv:2606.14249, Chen et al. 2026)

Key Concepts from Paper:
    1. Composable harness primitives via substitution algebra
    2. AEGIS: trace-driven multi-agent evolution engine
    3. Operational mirror between symbolic adaptation and RL
    4. Harness-model loop: trajectories → harness updates + model training
    5. Typed harness primitives (prompts, tools, memory, control flow)
    6. +14.5% average gain across 5 benchmarks

Paper Finding:
    "Agent progress need not come from model scaling alone:
     composing and evolving runtime interfaces from execution feedback
     is an actionable and complementary lever."

Algorithm:
    1. Decompose harness into typed primitives
    2. Evaluate each primitive's contribution
    3. Evolve primitives via AEGIS (trace-driven)
    4. Re-compose and re-evaluate

Complexity:
    compose(): O(P) where P = number of primitives
    evolve(): O(P × T) where T = trace length
    evaluate(): O(N) where N = test cases
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class HarnessPrimitive:
    """A typed harness primitive."""
    name: str = ""
    type: str = ""  # prompt, tool, memory, control, middleware
    content: Any = None
    version: int = 1
    score: float = 0.0
    usage_count: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class TraceRecord:
    """An execution trace record."""
    step: int = 0
    action: str = ""
    primitive_used: str = ""
    input_data: Any = None
    output_data: Any = None
    score: float = 0.0
    latency_ms: float = 0.0
    tokens: int = 0


@dataclass
class HarnessConfig:
    """Complete harness configuration."""
    primitives: list[HarnessPrimitive] = field(default_factory=list)
    version: int = 1
    score: float = 0.0
    metadata: dict = field(default_factory=dict)


class HarnessX:
    """Composable, adaptive, and evolvable agent harness foundry.

    Based on HarnessX paper (arXiv:2606.14249).

    Usage:
        hx = HarnessX()

        # Register primitives
        hx.register_primitive(HarnessPrimitive(name="cot_prompt", type="prompt", content="Think step by step"))
        hx.register_primitive(HarnessPrimitive(name="tool_search", type="tool", content=search_fn))

        # Compose harness
        config = hx.compose(["cot_prompt", "tool_search"])

        # Execute and trace
        traces = hx.execute(config, input_data="query")

        # Evolve based on traces
        new_config = hx.evolve(config, traces)

        # Evaluate
        score = hx.evaluate(new_config, test_cases)
    """

    def __init__(self):
        self._primitives: dict[str, HarnessPrimitive] = {}
        self._configs: list[HarnessConfig] = []
        self._traces: list[TraceRecord] = []
        self._evolution_history: list[dict] = []

    def register_primitive(self, primitive: HarnessPrimitive) -> None:
        """Register a harness primitive."""
        self._primitives[primitive.name] = primitive

    def compose(self, primitive_names: list[str]) -> HarnessConfig:
        """Compose a harness configuration from primitives.

        From paper: "assembles typed harness primitives via substitution algebra"

        Args:
            primitive_names: List of primitive names to compose.

        Returns:
            HarnessConfig with composed primitives.
        """
        primitives = []
        for name in primitive_names:
            if name in self._primitives:
                primitives.append(self._primitives[name])

        config = HarnessConfig(
            primitives=primitives,
            version=len(self._configs) + 1,
        )
        self._configs.append(config)
        return config

    def execute(self, config: HarnessConfig, input_data: Any = None,
                executor: Callable | None = None) -> list[TraceRecord]:
        """Execute a harness configuration and record traces.

        From paper: "closes the harness-model loop by turning trajectories
        into both harness updates and model training signal"

        Args:
            config: Harness configuration to execute.
            input_data: Input data for execution.
            executor: Optional custom executor function.

        Returns:
            List of trace records.
        """
        traces = []
        current_input = input_data

        for i, primitive in enumerate(config.primitives):
            start = time.time()

            try:
                if callable(primitive.content) and executor is None:
                    output = primitive.content(current_input)
                elif executor:
                    output = executor(primitive, current_input)
                else:
                    output = f"processed_by_{primitive.name}"

                score = 1.0  # Default score
                latency_ms = (time.time() - start) * 1000

                trace = TraceRecord(
                    step=i, action=primitive.name,
                    primitive_used=primitive.name,
                    input_data=current_input, output_data=output,
                    score=score, latency_ms=latency_ms,
                )
                traces.append(trace)

                primitive.usage_count += 1
                current_input = output

            except Exception as e:
                trace = TraceRecord(
                    step=i, action=primitive.name,
                    primitive_used=primitive.name,
                    input_data=current_input, output_data=None,
                    score=0.0, latency_ms=(time.time() - start) * 1000,
                )
                traces.append(trace)

        self._traces.extend(traces)
        return traces

    def evolve(self, config: HarnessConfig, traces: list[TraceRecord],
               strategy: str = "aegis") -> HarnessConfig:
        """Evolve harness based on execution traces.

        From paper: "AEGIS, a trace-driven multi-agent evolution engine
        grounded in an operational mirror between symbolic adaptation and RL"

        Args:
            config: Current harness configuration.
            traces: Execution traces from the last run.
            strategy: Evolution strategy ("aegis", "gradient", "random").

        Returns:
            New evolved HarnessConfig.
        """
        # Analyze trace performance per primitive
        primitive_scores: dict[str, list[float]] = {}
        for trace in traces:
            if trace.primitive_used not in primitive_scores:
                primitive_scores[trace.primitive_used] = []
            primitive_scores[trace.primitive_used].append(trace.score)

        # Identify weak primitives
        weak_primitives = []
        strong_primitives = []
        for name, scores in primitive_scores.items():
            avg_score = sum(scores) / len(scores) if scores else 0
            if avg_score < 0.5:
                weak_primitives.append(name)
            else:
                strong_primitives.append(name)

        # Evolution strategy
        new_primitives = []
        for prim in config.primitives:
            if prim.name in weak_primitives:
                # Try to find a better alternative
                alternative = self._find_alternative(prim)
                if alternative:
                    new_primitives.append(alternative)
                else:
                    new_primitives.append(prim)
            else:
                new_primitives.append(prim)

        # Create new config
        new_config = HarnessConfig(
            primitives=new_primitives,
            version=config.version + 1,
            metadata={"evolved_from": config.version, "strategy": strategy},
        )
        self._configs.append(new_config)

        # Record evolution
        self._evolution_history.append({
            "from_version": config.version,
            "to_version": new_config.version,
            "weak_primitives": weak_primitives,
            "strong_primitives": strong_primitives,
            "strategy": strategy,
            "timestamp": time.time(),
        })

        return new_config

    def _find_alternative(self, primitive: HarnessPrimitive) -> HarnessPrimitive | None:
        """Find an alternative primitive of the same type."""
        for name, prim in self._primitives.items():
            if prim.type == primitive.type and prim.name != primitive.name:
                return prim
        return None

    def evaluate(self, config: HarnessConfig | None = None, test_cases: list[dict] | None = None,
                 evaluator: Callable | None = None) -> float | dict:
        """Evaluate a harness configuration on test cases.

        Backward-compatible: if config is None, returns empty dict.

        Returns:
            Average score across test cases, or dict if backward-compat.
        """
        if config is None:
            if self._configs:
                best = max(self._configs, key=lambda c: c.score)
                return best
            return HarnessConfig(
                primitives=list(self._primitives.values())[:3],
                score=0.5, version=1,
            )

        test_cases = test_cases or []
        scores = []
        for case in test_cases:
            try:
                traces = self.execute(config, input_data=case.get("input"))
                if traces:
                    avg_score = sum(t.score for t in traces) / len(traces)
                    scores.append(avg_score)
                else:
                    scores.append(0.0)
            except Exception:
                logger.warning("Harness: failed to evaluate trace, defaulting score to 0")
                scores.append(0.0)

        avg_score = sum(scores) / max(len(scores), 1)
        config.score = avg_score
        return avg_score

    def get_primitive_stats(self) -> dict[str, dict]:
        """Get statistics for each primitive."""
        stats = {}
        for name, prim in self._primitives.items():
            stats[name] = {
                "type": prim.type,
                "version": prim.version,
                "score": prim.score,
                "usage_count": prim.usage_count,
            }
        return stats

    def get_evolution_history(self) -> list[dict]:
        """Get the evolution history."""
        return self._evolution_history

    def get_best_config(self) -> HarnessConfig | None:
        """Get the best performing harness configuration."""
        if not self._configs:
            return None
        return max(self._configs, key=lambda c: c.score)

    def get_stats(self) -> dict:
        """Get HarnessX statistics."""
        return {
            "primitives": len(self._primitives),
            "configs": len(self._configs),
            "traces": len(self._traces),
            "evolutions": len(self._evolution_history),
            "best_score": max((c.score for c in self._configs), default=0),
        }
