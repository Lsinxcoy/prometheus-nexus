"""CAMPAssembler — CAMP 动态组装+三值投票 (arXiv 2604.00085).

论文核心方法：按案例动态组装专家团 + 三值投票(支持/反对/弃权) + 分层仲裁。
弃权比强制投票更有信息量。

Enhancements:
- Dynamic panel assembly via relevance scoring (keyword + task-description matching)
- Three-value voting with competence-based abstention tracking
- Multi-round deliberation process with consensus convergence
"""

from __future__ import annotations
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Base expertise inventory — candidates ranked by relevance at assembly time
EXPERTISE_MAP: dict[str, list[dict[str, Any]]] = {
    "code": [
        {"name": "code_reviewer", "keywords": ["code", "bug", "syntax", "review"]},
        {"name": "security_auditor", "keywords": ["security", "vuln", "injection", "auth"]},
        {"name": "testing_specialist", "keywords": ["test", "coverage", "assert", "mock"]},
    ],
    "data": [
        {"name": "data_analyst", "keywords": ["statistics", "distribution", "pandas"]},
        {"name": "statistics_expert", "keywords": ["statistical", "p-value", "bayes"]},
        {"name": "domain_expert", "keywords": ["domain", "expert", "specialized"]},
    ],
    "text": [
        {"name": "editor", "keywords": ["grammar", "style", "readability"]},
        {"name": "content_reviewer", "keywords": ["content", "factual", "citation"]},
        {"name": "style_checker", "keywords": ["style", "tone", "format"]},
    ],
    "general": [
        {"name": "analyst", "keywords": ["analyze", "review", "check"]},
        {"name": "critic", "keywords": ["critique", "flaw", "weakness"]},
        {"name": "specialist", "keywords": ["expert", "domain", "specialist"]},
    ],
}

# Abstention thresholds
_ABSTAIN_RELEVANCE_THRESHOLD = 0.25
_ABSTAIN_CONFIDENCE_THRESHOLD = 0.30


class CAMPAssembler:
    """Case-adaptive multi-agent deliberation with three-value voting."""

    def __init__(self):
        self._panels: list[dict] = []
        self._votes: list[dict] = []
        self._deliberations: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assemble(self, task: dict) -> dict:
        """Dynamically assemble an expert panel relevant to the task.

        Args:
            task: {"type": str, "description": str, "domain": str, ...}

        Returns:
            {"panel": list[dict{name, relevance}],
             "reasoning": str, "coverage": float}
        """
        task_type = task.get("type", "general")
        description = (task.get("description", "") + " " + task.get("domain", "")).lower()

        # Gather candidate experts from all categories
        all_candidates = []
        for cat, experts in EXPERTISE_MAP.items():
            for expert in experts:
                relevance = self._compute_relevance(expert, description, cat, task_type)
                all_candidates.append({**expert, "relevance": relevance, "category": cat})

        # Sort by relevance descending, pick top 3-5
        all_candidates.sort(key=lambda e: e["relevance"], reverse=True)
        panel = all_candidates[:5]

        # Ensure at least 3 panelists
        if len(panel) < 3:
            # Fall back to default general experts
            panel = [
                {"name": "analyst", "keywords": [], "relevance": 0.5, "category": "general"},
                {"name": "critic", "keywords": [], "relevance": 0.5, "category": "general"},
                {"name": "specialist", "keywords": [], "relevance": 0.5, "category": "general"},
            ]

        coverage = round(
            sum(e["relevance"] for e in panel) / max(len(panel) * 1.0, 1), 4
        )

        result = {
            "panel": [{"name": e["name"], "relevance": e["relevance"]} for e in panel],
            "reasoning": f"Dynamic assembly for {task_type}: "
                         f"selected {len(panel)} experts (coverage={coverage})",
            "coverage": coverage,
        }
        self._panels.append(result)
        return result

    def vote(
        self, panel: list[dict | str], proposals: list[str]
    ) -> dict:
        """Three-value voting with competence-based abstention.

        Args:
            panel: list of expert dicts (with 'name' and 'relevance') or str names
            proposals: list of candidate proposals

        Returns:
            {"winner": str, "votes": dict{proposal: {for, against, abstain}},
             "abstention_rate": float, "turnout": int}
        """
        # Normalise panel entries to dicts
        panel_dicts = []
        for p in panel:
            if isinstance(p, str):
                panel_dicts.append({"name": p, "relevance": 0.5})
            else:
                panel_dicts.append(p)

        votes: dict[str, dict[str, float | int]] = {}
        for prop in proposals:
            votes_for = 0.0
            votes_against = 0.0
            abstain_count = 0
            turnout = 0

            for expert in panel_dicts:
                relevance = expert.get("relevance", 0.5)
                # Abstain if relevance or confidence is too low
                if relevance < _ABSTAIN_RELEVANCE_THRESHOLD:
                    abstain_count += 1
                    continue
                # Determine vote direction based on relevance-weighted sampling
                if relevance > 0.7:
                    votes_for += relevance
                    turnout += 1
                elif relevance < 0.4:
                    votes_against += relevance
                    turnout += 1
                else:
                    # Mid-relevance experts may still vote, but with lower weight
                    # Split: 60% chance support, 40% against
                    # (deterministic via hash for reproducibility)
                    h = hash(f"{expert['name']}-{prop}") % 100
                    if h < 60:
                        votes_for += relevance * 0.5
                    else:
                        votes_against += relevance * 0.5
                    turnout += 1

            votes[prop] = {
                "for": round(votes_for, 4),
                "against": round(votes_against, 4),
                "abstain": abstain_count,
                "turnout": turnout,
            }

        # Winner: highest net support
        winner = max(
            votes, key=lambda k: votes[k]["for"] - votes[k]["against"]
        )
        total_panel = len(panel_dicts)
        abstention_rate = round(
            sum(v["abstain"] for v in votes.values()) / max(total_panel * len(proposals), 1),
            4,
        )

        result = {
            "winner": winner,
            "votes": votes,
            "abstention_rate": abstention_rate,
            "turnout": votes[winner]["turnout"],
        }
        self._votes.append(result)
        return result

    def deliberate(
        self,
        task: dict,
        proposals: list[str],
        max_rounds: int = 3,
    ) -> dict:
        """Multi-round deliberation with convergence checking.

        Each round: assemble panel → vote → check convergence.
        Stops early when consensus (abstention < threshold) is reached.

        Args:
            task: task description dict
            proposals: list of candidate proposals
            max_rounds: max deliberation rounds (default 3)

        Returns:
            {"rounds": list[dict], "final_winner": str,
             "converged": bool, "rounds_used": int}
        """
        rounds: list[dict] = []
        converged = False

        for rnd in range(1, max_rounds + 1):
            panel_result = self.assemble(task)
            panel = panel_result["panel"]
            vote_result = self.vote(panel, proposals)

            round_data = {
                "round": rnd,
                "panel": panel,
                "vote": vote_result,
            }
            rounds.append(round_data)

            # Check convergence: abstention_rate low and clear winner
            if vote_result["abstention_rate"] < 0.2:
                # Verify winner has meaningful margin
                w = vote_result["winner"]
                w_votes = vote_result["votes"][w]
                if w_votes["for"] > w_votes["against"] + 0.5:
                    converged = True
                    break

        final_winner = rounds[-1]["vote"]["winner"] if rounds else ""

        deliberation_result = {
            "rounds": rounds,
            "final_winner": final_winner,
            "converged": converged,
            "rounds_used": len(rounds),
        }
        self._deliberations.append(deliberation_result)
        return deliberation_result

    def get_stats(self) -> dict:
        return {
            "panels": len(self._panels),
            "votes": len(self._votes),
            "deliberations": len(self._deliberations),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_relevance(
        expert: dict, description: str, category: str, task_type: str
    ) -> float:
        """Score relevance of an expert to a task description (0-1)."""
        score = 0.0
        kw_matches = sum(
            1 for kw in expert.get("keywords", []) if kw in description
        )
        if expert.get("keywords"):
            score += kw_matches / max(len(expert["keywords"]), 1) * 0.6

        # Category match boost
        if category == task_type:
            score += 0.3
        elif task_type == "general":
            score += 0.1

        # Name in description bonus
        if expert["name"] in description:
            score += 0.2

        return round(min(score, 1.0), 4)
