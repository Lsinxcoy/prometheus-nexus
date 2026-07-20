"""EDREReplicator — Equilibrium Distribution Replicator Dynamics.

Based on EDRE equilibrium theory from SkillSmith (arXiv:2606.01314):
    dx_i/dt = x_i * (f_i - f̄) + ε * ∇H(x)

Where:
    x_i = population share of strategy i
    f_i = fitness of strategy i
    f̄ = weighted average fitness
    ε = selection intensity
    H(x) = Shannon entropy (diversity pressure)

Uses RK4 integration for ODE stability.

Extended with:
- EcosystemState: skill-tool co-proposal space management
- _propose_coevolution(): propose skill-tool coevolution candidates
- _record_antipattern(): persistent anti-pattern recording
- Reflective atomic package creation
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import math
from collections import Counter, defaultdict
from typing import Any


# ── EcosystemState ───────────────────────────��────────────────────────────────


class EcosystemState:
    """Represents the skill-tool co-proposal space.

    Tracks:
    - _skill_space: dict mapping skill_name -> metadata (version, fitness, dependencies)
    - _tool_space: dict mapping tool_name -> metadata (capability, usage_count, slots)
    - _coevolution_candidates: list of (skill, tool, rationale, score) proposals
    - _antipatterns: list of recorded anti-patterns
    """

    def __init__(self):
        self._skill_space: dict[str, dict] = {}
        self._tool_space: dict[str, dict] = {}
        self._coevolution_candidates: list[dict] = []
        self._antipatterns: list[dict] = []
        self._generation = 0

    def register_skill(self, name: str, version: int = 1,
                       dependencies: list[str] = None,
                       fitness: float = 0.5) -> dict:
        """Register or update a skill in the ecosystem."""
        deps = dependencies or []
        existing = self._skill_space.get(name, {})
        self._skill_space[name] = {
            "name": name,
            "version": max(version, existing.get("version", 0)),
            "dependencies": deps,
            "fitness": fitness,
            "generation": self._generation,
        }
        return self._skill_space[name]

    def register_tool(self, name: str, capability: str = "generic",
                      slots: int = 1) -> dict:
        """Register or update a tool in the ecosystem."""
        existing = self._tool_space.get(name, {})
        self._tool_space[name] = {
            "name": name,
            "capability": capability,
            "usage_count": existing.get("usage_count", 0) + 1,
            "slots": slots,
            "generation": self._generation,
        }
        return self._tool_space[name]

    def get_skill_space(self) -> dict[str, dict]:
        return dict(self._skill_space)

    def get_tool_space(self) -> dict[str, dict]:
        return dict(self._tool_space)


# ── EDREReplicator (extended) ─────────────────────────────────────────────────


class EDREReplicator:
    """Equilibrium-based replicator dynamics with diversity pressure.

    Usage:
        edre = EDREReplicator()
        edre.replicate({"context": "coding"}, fitness=0.8)
        edre.replicate({"context": "research"}, fitness=0.6)
        stats = edre.get_stats()
    """

    def __init__(self, selection_intensity: float = 0.1,
                 diversity_pressure: float = 0.01,
                 ecosystem: EcosystemState = None):
        self._epsilon = selection_intensity
        self._diversity_coeff = diversity_pressure
        self._populations: dict[str, float] = {}
        self._fitnesses: dict[str, float] = {}
        self._replications: list[dict] = []
        self._generation = 0
        self._diversity_history: list[float] = []
        self._population_history: list[list[float]] = []

        # EDRE extensions
        self._ecosystem = ecosystem or EcosystemState()
        self._antipatterns: list[dict] = []
        self._coevolution_proposals: list[dict] = []
        self._reflective_packages: list[dict] = []

    # ── public API (unchanged) ────────────────────────────────────────────────

    def replicate(self, data: dict | None = None, fitness: float = 0.5):
        """Add/update a population with given fitness.

        NOTE: 调用方两种风格都可能出现 —— (a) fitness 放在 data 字典内
        (life.py:2492 `replicate({"context": ctx, "fitness": fitness_before})`),
        或 (b) 作为关键字参数传入 (文档示例 `replicate({"context": "coding"},
        fitness=0.8)`). 此处以 data["fitness"] 优先、缺失时回退到关键字参数
        (默认 0.5), 保证两种风格都得到真实适应度。否则 (a) 风格的 fitness
        会被静默丢弃、EDRE 每轮只记录常量 0.5, 选择压力退化为无差异 ——
        真实进化适应度信号丢失 (演化/监控盲区)。
        """
        data = data or {}
        context = data.get("context", "default")

        # 兼容: fitness 经 data["fitness"] 或关键字参数传入, 字典优先
        fitness = data.get("fitness", fitness)

        if context not in self._populations:
            self._populations[context] = 1.0

        self._fitnesses[context] = fitness
        self._generation += 1

        self._step_ode(dt=0.1)

        self._replications.append({"data": data, "fitness": fitness, "gen": self._generation})

        if self._populations:
            total = sum(self._populations.values())
            if total > 0:
                shares = [v / total for v in self._populations.values()]
                entropy = -sum(p * math.log(p + 1e-10) for p in shares if p > 0)
                self._diversity_history.append(entropy)

            self._population_history.append(list(self._populations.values()))

    def _replicator_derivatives(self, pops: dict[str, float]) -> dict[str, float]:
        """Compute replicator equation: dx_i/dt = x_i * (f_i - f̄) + ε * dH/dx_i."""
        total = sum(pops.values())
        if total <= 0:
            return {k: 0.0 for k in pops}

        shares = {k: v / total for k, v in pops.items()}
        avg_fitness = sum(shares.get(k, 0) * self._fitnesses.get(k, 0.5) for k in pops)

        derivs = {}
        for name in pops:
            x_i = shares.get(name, 0.0)
            f_i = self._fitnesses.get(name, 0.5)
            dH = -math.log(x_i + 1e-10) - 1.0
            derivs[name] = x_i * (f_i - avg_fitness) + self._diversity_coeff * dH
        return derivs

    def _step_ode(self, dt: float = 0.1):
        """Single RK4 step for replicator dynamics."""
        names = list(self._populations.keys())
        pops = dict(self._populations)

        k1 = self._replicator_derivatives(pops)

        pops_k2 = {n: max(1e-6, pops[n] + 0.5 * dt * k1.get(n, 0)) for n in names}
        k2 = self._replicator_derivatives(pops_k2)

        pops_k3 = {n: max(1e-6, pops[n] + 0.5 * dt * k2.get(n, 0)) for n in names}
        k3 = self._replicator_derivatives(pops_k3)

        pops_k4 = {n: max(1e-6, pops[n] + dt * k3.get(n, 0)) for n in names}
        k4 = self._replicator_derivatives(pops_k4)

        for n in names:
            new_pop = pops[n] + (dt / 6.0) * (k1.get(n, 0) + 2 * k2.get(n, 0) + 2 * k3.get(n, 0) + k4.get(n, 0))
            self._populations[n] = max(1e-6, new_pop)

    # ── skill-tool co-proposal ────────────────────────────────────────────────

    def _propose_coevolution(self, skill_name: str, tool_name: str,
                             rationale: str = None,
                             score: float = 0.5) -> dict:
        """Propose a skill-tool coevolution pair in the co-proposal space.

        Coevolution means the skill and tool jointly adapt: the skill learns
        to use the tool more effectively, and the tool evolves new capabilities
        based on skill demands.

        Implements the EDRE skill-tool co-adaptation dynamics from SkillSmith.
        The coevolution score is computed not just as static value but as
        the product of mutual fitness complementarity, weighted by the
        replicator dynamics shares.

        Args:
            skill_name: Name of the skill in the ecosystem.
            tool_name: Name of the tool in the ecosystem.
            rationale: Text describing why coevolution is beneficial.
            score: Coevolution score (0-1) based on fitness complementarity.

        Returns:
            {"skill": str, "tool": str, "rationale": str, "score": float,
             "generation": int, "adopted": bool, "mutual_fitness": float}
        """
        if rationale is None:
            rationale = f"Coevolution of {skill_name} with {tool_name}"

        # Register both in the ecosystem state if not already present
        self._ecosystem.register_skill(skill_name)
        self._ecosystem.register_tool(tool_name)

        # Compute coevolution benefit using replicator dynamics (EDRE §3.2)
        benefit = self.compute_coevolution_benefit(skill_name, tool_name)
        mutual_fitness = benefit["expected_benefit"]

        # Score adjusted by mutual fitness: even if initial score is low,
        # high complementarity boosts the proposal
        if mutual_fitness > 0.3:
            score = max(score, mutual_fitness)

        proposal = {
            "skill": skill_name,
            "tool": tool_name,
            "rationale": rationale,
            "score": round(score, 4),
            "mutual_fitness": round(mutual_fitness, 4),
            "generation": self._generation,
            "adopted": score >= 0.6,
        }
        self._coevolution_proposals.append(proposal)
        self._ecosystem._coevolution_candidates.append(proposal)

        # If adopted, apply co-evolution adaptation to both skill and tool
        if proposal["adopted"]:
            self._apply_coadaptation(skill_name, tool_name, mutual_fitness)

        return proposal

    def _apply_coadaptation(self, skill_name: str, tool_name: str,
                             mutual_fitness: float) -> None:
        """Apply coevolution adaptation: update skill fitness and tool usage.

        When a skill-tool pair is adopted, both entities receive a fitness
        boost proportional to the mutual fitness. This creates the positive
        feedback loop described in SkillSmith's coevolution framework.
        """
        # Update skill fitness with coevolution boost
        current_fitness = self._fitnesses.get(skill_name, 0.5)
        boost = mutual_fitness * 0.2  # 20% of mutual fitness as boost
        self._fitnesses[skill_name] = min(1.0, current_fitness + boost)

        # Update ecosystem registrations
        self._ecosystem.register_skill(skill_name, fitness=self._fitnesses[skill_name])
        self._ecosystem.register_tool(tool_name)

    def _record_antipattern(self, context: str,
                            pattern_description: str,
                            severity: str = "medium",
                            resolution: str = None) -> dict:
        """Record an anti-pattern that was detected during skill-tool coevolution.

        Anti-patterns are recurring negative patterns that reduce ecosystem
        fitness. Recording them enables future avoidance.

        Args:
            context: The context where the anti-pattern was observed.
            pattern_description: Description of the anti-pattern.
            severity: "low", "medium", or "high".
            resolution: Optional suggested resolution.

        Returns:
            {"context": str, "pattern": str, "severity": str,
             "resolution": str | None, "generation": int}
        """
        if severity not in ("low", "medium", "high"):
            severity = "medium"

        ap = {
            "context": context,
            "pattern": pattern_description,
            "severity": severity,
            "resolution": resolution or "",
            "generation": self._generation,
        }
        self._antipatterns.append(ap)
        self._ecosystem._antipatterns.append(ap)
        return ap

    # ── reflective atomic package creation ────────────────────────────────────

    def create_atomic_package(self, skill_name: str, tool_names: list[str],
                              fitness_gain: float = 0.0,
                              description: str = None) -> dict:
        """Create a reflective atomic package: bundled skill-tool combination.

        An atomic package is a self-contained unit that includes a skill and
        its coevolved tools, ready for deployment. The package records its
        generation and fitness contribution.

        Args:
            skill_name: Name of the skill to package.
            tool_names: List of tool names that coevolved with this skill.
            fitness_gain: Observed fitness gain from the package.
            description: Human-readable description.

        Returns:
            {"skill": str, "tools": list[str], "fitness_gain": float,
             "generation": int, "description": str, "package_id": int}
        """
        desc = description or f"Atomic package: {skill_name} + {', '.join(tool_names)}"

        pkg = {
            "package_id": len(self._reflective_packages),
            "skill": skill_name,
            "tools": list(tool_names),
            "fitness_gain": round(fitness_gain, 4),
            "generation": self._generation,
            "description": desc,
        }
        self._reflective_packages.append(pkg)

        # Update ecosystem registrations
        self._ecosystem.register_skill(skill_name, fitness=fitness_gain)
        for tool in tool_names:
            self._ecosystem.register_tool(tool)

        return pkg

    # ── alignment with EDRE paper: compute coevolution benefit ────────────────

    def compute_coevolution_benefit(self, skill: str, tool: str) -> dict:
        """Compute the expected benefit of a skill-tool coevolution proposal.

        Uses replicator dynamics to estimate how much fitness each would gain
        from coevolution, based on their current population shares.

        Args:
            skill: Skill name.
            tool: Tool name (used as context key).

        Returns:
            {"skill_share": float, "tool_fitness": float,
             "expected_benefit": float, "recommend": bool}
        """
        skill_share = self._populations.get(skill, 0.0)
        skill_fitness = self._fitnesses.get(skill, 0.5)

        # Derive tool "population" from its usage in the ecosystem
        tool_entry = self._ecosystem.get_tool_space().get(tool, {})
        tool_usage = tool_entry.get("usage_count", 0)
        tool_fitness = min(1.0, tool_usage / max(len(self._populations), 1))

        total = sum(self._populations.values()) or 1
        normalized_share = skill_share / total

        # Expected benefit: product of share-weighted fitness
        expected_benefit = round(normalized_share * (skill_fitness + tool_fitness) / 2.0, 4)

        return {
            "skill_share": round(normalized_share, 4),
            "tool_fitness": round(tool_fitness, 4),
            "expected_benefit": expected_benefit,
            "recommend": expected_benefit >= 0.3,
        }

    # ── original public helpers (unchanged) ───────────────────────────────────

    def get_shares(self) -> dict[str, float]:
        total = sum(self._populations.values())
        if total <= 0:
            return {}
        return {k: v / total for k, v in self._populations.items()}

    def get_dominant(self) -> str | None:
        if not self._populations:
            return None
        return max(self._populations, key=self._populations.get)

    def get_stats(self) -> dict:
        total = sum(self._populations.values())
        shares = self.get_shares()
        return {
            "replications": len(self._replications),
            "generation": self._generation,
            "species": len(self._populations),
            "diversity": self._diversity_history[-1] if self._diversity_history else 0,
            "dominant": self.get_dominant(),
            "shares": shares,
            # Extended stats
            "ecosystem_skills": len(self._ecosystem.get_skill_space()),
            "ecosystem_tools": len(self._ecosystem.get_tool_space()),
            "coevolution_proposals": len(self._coevolution_proposals),
            "antipatterns_recorded": len(self._antipatterns),
            "atomic_packages": len(self._reflective_packages),
        }
