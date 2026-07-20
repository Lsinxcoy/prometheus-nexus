"""ToolLoop — ReAct pattern tool execution loop.

Based on: "ReAct: Synergizing Reasoning and Acting in Language Models"
(arXiv:2210.03629, Yao et al. 2023)

Key Concepts from Paper:
    1. Thought → Action → Observation alternating cycle
    2. Thought: reasoning about what to do next
    3. Action: executing a tool/API call
    4. Observation: receiving environment feedback
    5. Interleaving reasoning and acting (not just one or the other)

Paper Finding:
    "ReAct outperforms Act-only on task success rate by 6%
     and outperforms Thought-only on F1 by 12%"

Algorithm:
    while not done:
        thought = reason(context, history)
        action = select_action(thought)
        observation = execute(action)
        history.append((thought, action, observation))
        if observation indicates success:
            done = True

Complexity: O(I) where I = max_iterations
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import time
from dataclasses import dataclass, field


@dataclass
class ReActStep:
    """A single ReAct step."""
    step: int = 0
    thought: str = ""
    action: str = ""
    observation: str = ""
    score: float = 0.0
    timestamp: float = 0.0


class ToolLoop:
    """ReAct-pattern tool execution loop.

    Based on ReAct paper (arXiv:2210.03629).

    Usage:
        loop = ToolLoop(max_iterations=5)
        result = loop.execute("solve puzzle")
        for step in result["steps"]:
            print(f"Thought: {step.thought}")
            print(f"Action: {step.action}")
            print(f"Observation: {step.observation}")
    """

    def __init__(self, max_iterations: int = 5, max_retries: int = 2):
        """Initialize the ReAct loop.

        Args:
            max_iterations: Maximum thought-action-observation cycles.
            max_retries: Maximum retries per action on failure.
        """
        self._max_iter = max_iterations
        self._max_retries = max_retries
        self._loops: list[dict] = []

    def execute(self, task: str, tools: list[dict] | None = None,
                executor=None) -> dict:
        """Execute a task using the ReAct loop.

        Args:
            task: The task to accomplish.
            tools: Available tools (list of dicts with name, description, fn).
            executor: Optional custom executor function.

        Returns:
            Dict with steps, result, and metadata.
        """
        tools = tools or []
        steps: list[ReActStep] = []
        context = {"task": task, "tools": [t.get("name", "") for t in tools]}
        history = []

        for i in range(self._max_iter):
            # THOUGHT: Reason about what to do
            thought = self._think(task, context, history, i)

            # ACTION: Select and execute action
            action, observation, score = self._act(
                thought, tools, executor, context
            )

            # Record step
            step = ReActStep(
                step=i, thought=thought, action=action,
                observation=observation, score=score,
                timestamp=time.time(),
            )
            steps.append(step)
            history.append({"thought": thought, "action": action, "observation": observation})

            # Check if done
            if self._is_done(observation, score):
                break

        result = {
            "task": task,
            "steps": steps,
            "iterations": len(steps),
            "final_observation": steps[-1].observation if steps else "",
            "total_score": sum(s.score for s in steps),
            "completed": len(steps) < self._max_iter,
        }
        self._loops.append(result)
        return result

    def _think(self, task: str, context: dict, history: list, step: int) -> str:
        """Generate a thought about what to do next.

        In a real system, this would call an LLM.
        Here we implement rule-based reasoning.
        """
        if not history:
            return f"Starting task: {task}. I need to identify the right approach."

        last = history[-1]
        if last.get("observation", "").startswith("ERROR"):
            return f"Previous action failed. Trying alternative approach for: {task}"

        if step >= 2:
            return f"Progress made. Evaluating if task {task} is complete."

        return f"Analyzing task {task} based on available tools: {context.get('tools', [])}"

    def _act(self, thought: str, tools: list[dict], executor, context: dict) -> tuple[str, str, float]:
        """Execute an action based on the thought."""
        if tools:
            # Select first available tool
            tool = tools[0]
            tool_name = tool.get("name", "unknown")
            tool_fn = tool.get("fn")

            if tool_fn:
                try:
                    result = tool_fn(context.get("task", ""))
                    return tool_name, str(result), 0.8
                except Exception as e:
                    return tool_name, f"ERROR: {e}", 0.0
            else:
                return tool_name, f"Executed {tool_name} (no fn)", 0.5

        if executor:
            try:
                result = executor(thought, context)
                return "custom", str(result), 0.7
            except Exception as e:
                return "custom", f"ERROR: {e}", 0.0

        # Default: no tools available
        return "none", f"No tools available for: {thought[:50]}", 0.1

    def _is_done(self, observation: str, score: float) -> bool:
        """Check if the task is complete."""
        if score >= 0.9:
            return True
        if "complete" in observation.lower() or "success" in observation.lower():
            return True
        if "no tools" in observation.lower():
            return True  # No tools = nothing more to do
        if "ERROR" in observation:
            return False
        return False

    def get_stats(self) -> dict:
        return {"loops": len(self._loops)}
