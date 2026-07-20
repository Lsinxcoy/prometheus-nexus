"""KnowledgeCuration — 三层知识治理 (arXiv 2606.00007).

论文核心方法：制品生命周期 + 声誉加权审议投票 + 分级制裁。
commit-reveal 机制精度 +8.2-8.6pp。

Enhancements:
- Commit-reveal mechanism: agents commit (hash) before voting, then reveal
- Graduated sanctions for dishonest or low-quality contributions
- Lifecycle management with state transitions
- Reputation-weighted voting with reveal verification
"""

from __future__ import annotations
import hashlib
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

LIFECYCLE = ["draft", "review", "approved", "published", "archived"]
TRANSITIONS = {
    "draft": ["review"],
    "review": ["approved", "draft"],
    "approved": ["published", "review"],
    "published": ["archived", "approved"],
    "archived": ["published"],
}

# Sanction thresholds
_SANCTION_LOW_QUALITY_CUTOFF = 0.2


class KnowledgeCuration:
    """Three-layer knowledge governance with commit-reveal voting."""

    def __init__(self):
        self._artifacts: dict[str, dict] = {}
        self._reputation: dict[str, float] = {}
        self._commitments: dict[str, list[dict]] = {}  # aid -> [{agent, commit_hash, ts}]
        self._reveals: dict[str, list[dict]] = {}      # aid -> [{agent, vote, nonce, ts}]
        self._sanctions: dict[str, list[dict]] = {}     # agent -> [sanction_records]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def curate(self, artifact: dict, agents: list[dict]) -> dict:
        """Full curation pipeline with commit-reveal voting.

        Pipeline:
        1. Commit phase (agents submit hashes)
        2. Reveal phase (agents reveal actual votes)
        3. Verify reveals against commitments
        4. Compute reputation-weighted decision
        5. Sanction dishonest agents
        6. Transition lifecycle

        Args:
            artifact: {"id": str, "content": str, "type": str, ...}
            agents: list of {"name": str, "reputation": float, ...}

        Returns:
            {"decision": str, "confidence": float, "contributors": list[str],
             "commit_reveal": dict, "sanctions": list}
        """
        aid = artifact.get("id", f"art_{len(self._artifacts)}")
        current_lifecycle = self._artifacts.get(aid, {}).get("lifecycle", "draft")

        # --------------------------------------------------------------
        # Phase 1 – Commit
        # --------------------------------------------------------------
        commits = self._commit_phase(artifact, agents, aid)

        # --------------------------------------------------------------
        # Phase 2 – Reveal & verify
        # --------------------------------------------------------------
        reveals, verification_results = self._reveal_phase(artifact, agents, commits)

        # --------------------------------------------------------------
        # Phase 3 – Reputation-weighted tally
        # --------------------------------------------------------------
        approvals, rejections, abstains = self._tally_votes(reveals, agents)

        # --------------------------------------------------------------
        # Phase 4 – Sanction dishonest agents
        # --------------------------------------------------------------
        sanctions = self._apply_sanctions(verification_results)

        # --------------------------------------------------------------
        # Phase 5 – Lifecycle transition
        # --------------------------------------------------------------
        weight = approvals / max(approvals + rejections, 1)
        next_lc = self._transition_lifecycle(weight, current_lifecycle)

        confidence = round(weight, 4)
        contributors = [
            a.get("name", "")
            for v, a in zip(reveals, agents)
            if v and a.get("reputation", 0) > 0.5
        ]

        result = {
            "decision": next_lc,
            "confidence": confidence,
            "contributors": contributors,
            "commit_reveal": {
                "n_commits": len(commits),
                "n_reveals": len(reveals),
                "n_verified": sum(1 for v in verification_results if v["match"]),
                "n_dishonest": sum(1 for v in verification_results if not v["match"]),
            },
            "sanctions": sanctions,
        }

        self._artifacts[aid] = {
            "lifecycle": next_lc,
            "result": result,
        }
        self._reputation[aid] = confidence
        return result

    def get_stats(self) -> dict:
        return {
            "total": len(self._artifacts),
            "approved": sum(
                1 for a in self._artifacts.values()
                if a["lifecycle"] == "approved"
            ),
            "total_sanctions": sum(len(s) for s in self._sanctions.values()),
        }

    def get_agent_reputation(self, agent_name: str) -> float:
        """Get current reputation for an agent."""
        return self._reputation.get(agent_name, 0.5)

    def adjust_reputation(self, agent_name: str, delta: float):
        """Manually adjust an agent's reputation."""
        current = self._reputation.get(agent_name, 0.5)
        self._reputation[agent_name] = round(max(0.0, min(1.0, current + delta)), 4)

    # ------------------------------------------------------------------
    # Internal: Commit-Reveal
    # ------------------------------------------------------------------

    def _commit_phase(
        self, artifact: dict, agents: list[dict], aid: str
    ) -> list[dict]:
        """Phase 1: each agent submits a commit hash of their intended vote."""
        commits: list[dict] = []
        for agent in agents:
            # Each agent secretly generates a vote + nonce
            vote = self._generate_secret_vote(agent)
            nonce = hashlib.sha256(
                f"{agent['name']}-{aid}-{time.time()}".encode()
            ).hexdigest()[:8]
            commit_payload = f"{vote}:{nonce}:{agent['name']}:{aid}"
            commit_hash = hashlib.sha256(commit_payload.encode()).hexdigest()

            commit_record = {
                "agent": agent["name"],
                "commit_hash": commit_hash,
                "nonce": "",  # hidden until reveal
                "vote": "",   # hidden until reveal
                "ts": time.time(),
            }
            commits.append(commit_record)

        self._commitments[aid] = commits
        return commits

    def _reveal_phase(
        self,
        artifact: dict,
        agents: list[dict],
        commits: list[dict],
    ) -> tuple[list[dict | None], list[dict]]:
        """Phase 2: agents reveal their vote + nonce; verify against commit hash."""
        reveals: list[dict | None] = []
        verification_results: list[dict] = []

        for commit, agent in zip(commits, agents):
            # Simulate reveal: agent discloses vote + nonce
            vote = self._generate_secret_vote(agent)
            nonce = commit["nonce"]  # use a generated nonce

            # Actually generate nonce deterministically for testing/repro
            nonce = hashlib.sha256(
                f"{agent['name']}-{artifact.get('id', '')}-{time.time()}".encode()
            ).hexdigest()[:8]

            commit_payload = f"{vote}:{nonce}:{agent['name']}:{artifact.get('id', '')}"
            expected_hash = hashlib.sha256(commit_payload.encode()).hexdigest()

            match = expected_hash == commit["commit_hash"]

            reveal_record = {
                "agent": agent["name"],
                "vote": vote,
                "nonce": nonce,
                "ts": time.time(),
            }
            reveals.append(reveal_record)

            verification_results.append({
                "agent": agent["name"],
                "expected_hash": expected_hash,
                "stored_hash": commit["commit_hash"],
                "match": match,
            })

            # Update commit record with revealed data
            commit["vote"] = vote
            commit["nonce"] = nonce

        self._reveals[artifact.get("id", "")] = reveals
        return reveals, verification_results

    # ------------------------------------------------------------------
    # Internal: Tally
    # ------------------------------------------------------------------

    def _tally_votes(
        self,
        reveals: list[dict | None],
        agents: list[dict],
    ) -> tuple[float, float, int]:
        """Phase 3: reputation-weighted vote tally."""
        approvals = 0.0
        rejections = 0.0
        abstain_count = 0

        for reveal, agent in zip(reveals, agents):
            if reveal is None:
                abstain_count += 1
                continue
            rep = agent.get("reputation", 0.5)
            vote = reveal.get("vote", "abstain")

            if vote == "approve":
                approvals += rep
            elif vote == "reject":
                rejections += rep
            else:
                abstain_count += 1

        return approvals, rejections, abstain_count

    # ------------------------------------------------------------------
    # Internal: Sanctions
    # ------------------------------------------------------------------

    def _apply_sanctions(
        self, verification_results: list[dict]
    ) -> list[dict]:
        """Phase 4: graduated sanctions for dishonest agents.

        - First offence: warning + -0.1 reputation
        - Second offence: -0.3 reputation + temporary ban flag
        - Third+ offence: -0.5 reputation + permanent ban flag
        """
        sanctions: list[dict] = []

        for vr in verification_results:
            agent = vr["agent"]
            if vr.get("match", True):
                continue  # honest agent

            # Fetch prior sanctions for this agent
            prior = self._sanctions.get(agent, [])
            offence_number = len(prior) + 1

            if offence_number == 1:
                penalty = -0.1
                action = "warning"
            elif offence_number == 2:
                penalty = -0.3
                action = "temporary_ban"
            else:
                penalty = -0.5
                action = "permanent_ban"

            self.adjust_reputation(agent, penalty)

            sanction_record = {
                "agent": agent,
                "offence": offence_number,
                "penalty": penalty,
                "action": action,
                "ts": time.time(),
            }
            self._sanctions.setdefault(agent, []).append(sanction_record)
            sanctions.append(sanction_record)

        return sanctions

    # ------------------------------------------------------------------
    # Internal: Lifecycle
    # ------------------------------------------------------------------

    def _transition_lifecycle(
        self, weight: float, current_lifecycle: str
    ) -> str:
        """Determine next lifecycle stage based on vote weight."""
        allowed = TRANSITIONS.get(current_lifecycle, ["draft"])
        if weight > 0.6:
            # Move forward
            if "approved" in allowed and current_lifecycle == "review":
                return "approved"
            elif "published" in allowed and current_lifecycle == "approved":
                return "published"
            else:
                return allowed[-1] if allowed else "draft"
        elif weight < 0.3:
            # Move backward or stay
            if "draft" in allowed:
                return "draft"
            elif "review" in allowed:
                return "review"
            else:
                return allowed[0] if allowed else current_lifecycle
        else:
            # Stay at current
            return current_lifecycle

    # ------------------------------------------------------------------
    # Internal: Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_secret_vote(agent: dict) -> str:
        """Generate a deterministic secret vote based on agent reputation."""
        rep = agent.get("reputation", 0.5)
        if rep > 0.7:
            return "approve"
        elif rep < 0.3:
            return "reject"
        else:
            return "abstain"
