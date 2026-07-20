"""AgentForest — Agent forest with sample-vote and performance scaling.

Based on: "More Agents Is All You Need" (Ye et al., 2024 | TMLR)

Key Concepts from Paper:
    1. Sample-vote: generate N samples, take majority vote
    2. Simply increasing agent count improves performance
    3. Effect is orthogonal to complex methods (combinable)
    4. Scaling law: performance increases with log(num_agents)

Algorithm:
    1. Register agents with capabilities and performance history
    2. For a task, sample K agents
    3. Each agent generates a response
    4. Majority vote determines final answer
    5. Track voting accuracy for agent ranking
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class AgentProfile:
    name: str = ""
    capabilities: list[str] = field(default_factory=list)
    score: float = 0.5
    tasks_completed: int = 0
    votes_won: int = 0
    votes_total: int = 0
    created_at: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.votes_won / max(self.votes_total, 1)


@dataclass
class VoteResult:
    winner: str = ""
    vote_count: int = 0
    total_votes: int = 0
    agreement: float = 0.0
    votes: dict[str, int] = field(default_factory=dict)


class AgentForest:
    """Agent forest with sample-vote and performance scaling.

    Based on "More Agents Is All You Need" (Ye 2024).

    Usage:
        forest = AgentForest()
        forest.add_agent("agent_a", {"capabilities": ["math"]})
        forest.add_agent("agent_b", {"capabilities": ["math"]})
        forest.add_agent("agent_c", {"capabilities": ["math"]})

        result = forest.sample_vote(
            task="What is 2+2?",
            sample_count=3,
            responses=["4", "4", "5"],
        )
        print(result.winner)  # "4"
        print(result.agreement)  # 0.67
    """

    def __init__(self):
        self._agents: dict[str, AgentProfile] = {}
        self._votes: list[dict] = []

    def add_agent(self, name: str, config: dict | None = None):
        cfg = config or {}
        self._agents[name] = AgentProfile(
            name=name,
            capabilities=cfg.get("capabilities", []),
            score=cfg.get("score", 0.5),
            created_at=time.time(),
        )

    def remove_agent(self, name: str):
        self._agents.pop(name, None)

    def record_performance(self, agent_name: str, score: float):
        if agent_name in self._agents:
            agent = self._agents[agent_name]
            agent.score = agent.score * 0.8 + score * 0.2
            agent.tasks_completed += 1

    def sample_agents(self, count: int, capability: str | None = None) -> list[str]:
        candidates = []
        for name, agent in self._agents.items():
            if capability and capability not in agent.capabilities:
                continue
            candidates.append(name)

        if not candidates:
            return []

        candidates.sort(key=lambda n: self._agents[n].score, reverse=True)
        return candidates[:count]

    def sample_vote(self, task: str, sample_count: int = 3,
                    responses: list[str] | None = None,
                    agent_names: list[str] | None = None) -> VoteResult:
        if not responses:
            responses = []

        vote_counts = Counter(responses)
        total = len(responses)

        if not vote_counts:
            return VoteResult()

        winner, win_count = vote_counts.most_common(1)[0]
        agreement = win_count / max(total, 1)

        if agent_names:
            for i, name in enumerate(agent_names):
                if name in self._agents:
                    agent = self._agents[name]
                    agent.votes_total += 1
                    if i < len(responses) and responses[i] == winner:
                        agent.votes_won += 1

        result = VoteResult(
            winner=winner,
            vote_count=win_count,
            total_votes=total,
            agreement=agreement,
            votes=dict(vote_counts),
        )

        self._votes.append({
            "task": task[:50],
            "winner": winner,
            "agreement": agreement,
            "sample_count": sample_count,
        })

        return result

    def get_agent_rankings(self, capability: str | None = None) -> list[dict]:
        agents = []
        for name, agent in self._agents.items():
            if capability and capability not in agent.capabilities:
                continue
            agents.append({
                "name": name,
                "score": agent.score,
                "tasks": agent.tasks_completed,
                "win_rate": agent.win_rate,
            })
        agents.sort(key=lambda a: a["score"], reverse=True)
        return agents

    def get_stats(self) -> dict:
        return {
            "agents": len(self._agents),
            "total_votes": len(self._votes),
            "avg_agreement": sum(v["agreement"] for v in self._votes) / max(len(self._votes), 1),
        }
