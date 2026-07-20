"""A2ABasic — Agent-to-Agent protocol basics.

Based on: MiMo Knowledge #67 (A2A + MCP = 完整协议栈)

A2A = agent-to-agent (semantic interoperability)
MCP = agent-to-tool (mechanical interoperability)

A2A provides:
    - Intent alignment between agents
    - Capability negotiation
    - Asynchronous task delegation
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass
class AgentCapability:
    name: str = ""
    description: str = ""
    input_types: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)


@dataclass
class A2ATask:
    task_id: str = ""
    description: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    requester: str = ""
    executor: str = ""
    created_at: float = 0.0


class A2ABasic:
    """Basic Agent-to-Agent protocol.

    Usage:
        a2a = A2ABasic()
        a2a.register_agent("agent_a", [AgentCapability(name="search")])
        a2a.register_agent("agent_b", [AgentCapability(name="write")])
        task = a2a.delegate_task("search for papers", required=["search"])
        a2a.complete_task(task.task_id, "Found 5 papers")
    """

    def __init__(self):
        self._agents: dict[str, list[AgentCapability]] = {}
        self._tasks: dict[str, A2ATask] = {}
        self._history: list[dict] = []

    def register_agent(self, agent_id: str, capabilities: list[AgentCapability]):
        self._agents[agent_id] = capabilities

    def delegate_task(self, description: str, required: list[str] = None,
                      requester: str = "system") -> A2ATask:
        required = required or []
        executor = self._find_capable_agent(required)

        task = A2ATask(
            task_id="task_%d" % int(time.time() * 1000),
            description=description,
            required_capabilities=required,
            status=TaskStatus.PENDING if executor else TaskStatus.REJECTED,
            requester=requester,
            executor=executor or "",
            created_at=time.time(),
        )
        self._tasks[task.task_id] = task
        return task

    def _find_capable_agent(self, required: list[str]) -> str | None:
        for agent_id, capabilities in self._agents.items():
            agent_caps = {c.name for c in capabilities}
            if all(r in agent_caps for r in required):
                return agent_id
        return None

    def complete_task(self, task_id: str, result: str):
        if task_id in self._tasks:
            self._tasks[task_id].status = TaskStatus.COMPLETED
            self._tasks[task_id].result = result
            self._history.append({"task": task_id, "result": result[:100]})

    def get_pending_tasks(self) -> list[A2ATask]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]

    def get_stats(self) -> dict:
        return {"agents": len(self._agents), "tasks": len(self._tasks),
                "completed": sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)}
