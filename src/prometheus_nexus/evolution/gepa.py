"""GEPA — Gradient-Enhanced Parameter Adaptation + PBT Population Training.

GEPA implements two evolution strategies:

1. GEPA (default): Gradient-Enhanced Parameter Adaptation — finite-difference
   gradient estimation with momentum for continuous parameter optimization.

2. PBT (Population-Based Training, arXiv:1711.09846): Maintains a population
   of parameter sets, applies exploit/explore via truncation selection +
   perturbation, no gradient computation.

PBT Algorithm (from arXiv:1711.09846):
    1. Initialize population of N agents with random params
    2. Each agent trains independently
    3. Every K steps: truncation selection (bottom 20% replaced)
       - exploit: copy params from top 20%
       - explore: perturb copied params (add noise)
    4. Continue until convergence

GEPA Algorithm:
    for each round:
        fitness = evaluate(params)
        for each param_i:
            gradient = (f(params+eps) - f(params-eps)) / (2*eps)
        velocity = beta * velocity + lr * gradient
        params = clip(params + velocity, min, max)

Usage:
    # GEPA mode (gradient-based)
    gepa = GEPA(evaluate_fn=my_fitness_fn)
    result = gepa.evolve(context="optimize")

    # PBT mode (population-based, arXiv 1711.09846)
    gepa = GEPA(population_size=10, method="pbt")
    result = gepa.evolve(context="optimize")
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GradientRecord:
    """A single gradient computation record."""
    round_num: int = 0
    parameters: Dict[str, float] = field(default_factory=dict)
    gradient: Dict[str, float] = field(default_factory=dict)
    fitness: float = 0.0
    learning_rate: float = 0.0
    timestamp: float = 0.0


@dataclass
class GEPAEvolutionResult:
    """Result of a GEPA evolution step."""
    method: str = "gepa"
    improvement: float = 0.0
    fitness_before: float = 0.0
    fitness_after: float = 0.0
    gradient_norm: float = 0.0
    parameters: Dict[str, float] = field(default_factory=dict)
    gradient: Dict[str, float] = field(default_factory=dict)
    velocity: Dict[str, float] = field(default_factory=dict)
    population: List[Dict[str, float]] | None = None
    population_fitness: List[float] | None = None
    details: str = ""


class GradientEnhancedParameterAdaptation:
    """Gradient-Enhanced Parameter Adaptation with PBT option.

    Supports both gradient-based (GEPA) and population-based (PBT) evolution.
    PBT mode implements arXiv:1711.09846 — population-based training with
    truncation selection, exploit (copy from top), explore (perturb).
    """

    def __init__(self, param_ranges: Optional[Dict[str, Tuple[float, float]]] = None,
                 evaluate_fn: Optional[Callable] = None,
                 method: str = "gepa",
                 population_size: int = 10,
                 learning_rate: float = 0.01, momentum: float = 0.9,
                 epsilon: float = 1e-4, max_gradient_norm: float = 1.0,
                 lr_decay: float = 0.99, lr_min: float = 1e-6,
                 pbt_exploit_topk: float = 0.2,
                 pbt_perturb_std: float = 0.1):
        """Initialize GEPA/PBT.

        Args:
            param_ranges: Dict of param_name -> (min, max) bounds.
            evaluate_fn: Function that takes (context, params) -> fitness.
            method: "gepa" (gradient) or "pbt" (population, arXiv 1711.09846).
            population_size: Number of agents in PBT population.
            learning_rate: Initial learning rate (GEPA mode).
            momentum: Momentum coefficient (GEPA mode).
            epsilon: Finite-difference step size (GEPA mode).
            max_gradient_norm: Gradient clipping threshold (GEPA mode).
            lr_decay: Learning rate decay per round (GEPA mode).
            lr_min: Minimum learning rate (GEPA mode).
            pbt_exploit_topk: Top fraction to copy from in PBT exploit step.
            pbt_perturb_std: Std dev of Gaussian noise for PBT explore step.
        """
        self._param_ranges = param_ranges or self._default_param_ranges()
        self._evaluate_fn = evaluate_fn
        self._method = method
        self._lr = learning_rate
        self._momentum = momentum
        self._epsilon = epsilon
        self._max_grad_norm = max_gradient_norm
        self._lr_decay = lr_decay
        self._lr_min = lr_min
        self._pbt_population_size = population_size
        self._pbt_exploit_topk = pbt_exploit_topk
        self._pbt_perturb_std = pbt_perturb_std

        # GEPA state
        self._params: Dict[str, float] = {}
        self._velocity: Dict[str, float] = {}
        for name, (lo, hi) in self._param_ranges.items():
            self._params[name] = (lo + hi) / 2.0
            self._velocity[name] = 0.0

        # PBT state — population of parameter dicts
        self._population: List[Dict[str, float]] = []
        self._population_fitness: List[float] = []

        # History
        self._history: List[GradientRecord] = []
        self._fitness_history: List[float] = []
        self._best_fitness = float('-inf')
        self._best_params: Dict[str, float] = {}
        self._round = 0
        self._consecutive_no_improve = 0

    def _default_param_ranges(self) -> Dict[str, Tuple[float, float]]:
        return {
            "exploration_rate": (0.01, 0.5),
            "learning_rate": (0.001, 0.1),
            "temperature": (0.1, 1.0),
            "weight_decay": (0.0, 0.01),
            "attention_scale": (0.5, 2.0),
            "memory_weight": (0.1, 0.9),
            "innovation_rate": (0.01, 0.3),
            "stability_factor": (0.5, 1.0),
        }

    def _random_params(self) -> Dict[str, float]:
        """Sample random parameters from ranges (PBT initialization)."""
        params = {}
        for name, (lo, hi) in self._param_ranges.items():
            params[name] = lo + random.random() * (hi - lo)
        return params

    def _init_pbt_population(self) -> None:
        """Initialize PBT population with random parameter sets."""
        self._population = [self._random_params() for _ in range(self._pbt_population_size)]
        self._population_fitness = [float('-inf')] * self._pbt_population_size

    def _pbt_step(self, context: str, evaluate_fn: Optional[Callable]) -> Dict[str, float]:
        """Execute one PBT step: evaluate, exploit/explore, return best params.

        Implements the core PBT loop from arXiv:1711.09846:
        1. Evaluate all agents
        2. Truncation selection: bottom 20% are replaced
        3. Exploit: replaced agents copy from top 20%
        4. Explore: copied params are perturbed with Gaussian noise
        """
        if not self._population:
            self._init_pbt_population()

        eval_fn = evaluate_fn or self._evaluate_fn

        # Step 1: Evaluate all agents
        for i in range(len(self._population)):
            fitness = self._evaluate_params(context, self._population[i], eval_fn)
            self._population_fitness[i] = fitness

        # Step 2-4: Truncation selection (PBT core)
        n = len(self._population)
        n_exploit = max(1, int(n * self._pbt_exploit_topk))  # top 20%
        n_explore = max(1, int(n * self._pbt_exploit_topk))  # bottom 20%

        # Sort by fitness
        sorted_indices = sorted(range(n), key=lambda i: self._population_fitness[i], reverse=True)
        top_indices = sorted_indices[:n_exploit]
        bottom_indices = sorted_indices[-n_explore:]

        # Replace bottom agents with mutated top agents
        for i in bottom_indices:
            # Exploit: copy from a random top agent
            donor_idx = random.choice(top_indices)
            new_params = dict(self._population[donor_idx])

            # Explore: perturb each parameter with Gaussian noise
            for name in new_params:
                lo, hi = self._param_ranges[name]
                noise = random.gauss(0, self._pbt_perturb_std * (hi - lo))
                new_params[name] = max(lo, min(hi, new_params[name] + noise))

            self._population[i] = new_params

        # Return best params of this round
        best_idx = sorted_indices[0]
        self._best_params = dict(self._population[best_idx])
        self._best_fitness = max(self._best_fitness, self._population_fitness[best_idx])

        logger.debug("PBT step: best=%.4f, pop_avg=%.4f",
                     self._population_fitness[best_idx],
                     sum(self._population_fitness) / n)

        return self._population[best_idx]

    def evolve(self, context: str = "", evaluate_fn: Optional[Callable] = None,
               current_fitness: float = 0.0) -> GEPAEvolutionResult:
        """Perform one evolution step using the selected method.

        Args:
            context: Task context for evaluation.
            evaluate_fn: Override evaluation function.
            current_fitness: Current fitness for comparison.

        Returns:
            GEPAEvolutionResult with improvement metrics.
        """
        self._round += 1
        eval_fn = evaluate_fn or self._evaluate_fn

        if self._method == "pbt":
            return self._evolve_pbt(context, eval_fn)
        return self._evolve_gepa(context, eval_fn)

    def _evolve_pbt(self, context: str, eval_fn: Optional[Callable]) -> GEPAEvolutionResult:
        """PBT evolution step."""
        best_params = self._pbt_step(context, eval_fn)

        best_fitness = self._best_fitness
        # Compute population stats
        pop_avg = sum(self._population_fitness) / max(len(self._population_fitness), 1)
        pop_std = math.sqrt(
            sum((f - pop_avg) ** 2 for f in self._population_fitness) / max(len(self._population_fitness), 1)
        ) if len(self._population_fitness) > 1 else 0.0

        self._fitness_history.append(best_fitness)

        return GEPAEvolutionResult(
            method="pbt",
            improvement=max(0, best_fitness - (self._fitness_history[-2] if len(self._fitness_history) > 1 else 0)),
            fitness_before=self._fitness_history[-2] if len(self._fitness_history) > 1 else 0.0,
            fitness_after=best_fitness,
            gradient_norm=0.0,
            parameters=best_params,
            gradient={},
            velocity={},
            population=self._population,
            population_fitness=self._population_fitness,
            details=f"PBT: pop={len(self._population)}, avg={pop_avg:.4f}, std={pop_std:.4f}, best={best_fitness:.4f}",
        )

    def _evolve_gepa(self, context: str, eval_fn: Optional[Callable]) -> GEPAEvolutionResult:
        """Gradient-based GEPA evolution step."""
        fitness_before = self._evaluate(context, eval_fn)
        self._fitness_history.append(fitness_before)

        gradient = self._compute_gradient(context, eval_fn)

        grad_norm = self._gradient_norm(gradient)
        if grad_norm > self._max_grad_norm:
            clip_ratio = self._max_grad_norm / grad_norm
            gradient = {k: v * clip_ratio for k, v in gradient.items()}

        new_params = {}
        new_velocity = {}
        for name in self._params:
            new_velocity[name] = (
                self._momentum * self._velocity[name]
                + self._lr * gradient.get(name, 0.0)
            )
            new_params[name] = self._params[name] + new_velocity[name]
            lo, hi = self._param_ranges[name]
            new_params[name] = max(lo, min(hi, new_params[name]))

        self._params = new_params
        self._velocity = new_velocity

        fitness_after = self._evaluate(context, eval_fn)
        improvement = fitness_after - fitness_before

        if improvement > 0:
            self._consecutive_no_improve = 0
        else:
            self._consecutive_no_improve += 1
            if self._consecutive_no_improve >= 3:
                self._lr = max(self._lr_min, self._lr * 0.5)

        self._lr = max(self._lr_min, self._lr * self._lr_decay)

        if fitness_after > self._best_fitness:
            self._best_fitness = fitness_after
            self._best_params = dict(self._params)
            self._consecutive_no_improve = 0

        record = GradientRecord(
            round_num=self._round,
            parameters=dict(self._params),
            gradient=dict(gradient),
            fitness=fitness_after,
            learning_rate=self._lr,
            timestamp=time.time(),
        )
        self._history.append(record)
        if len(self._history) > 1000:
            self._history = self._history[-500:]
            self._fitness_history = self._fitness_history[-500:]

        return GEPAEvolutionResult(
            method="gepa",
            improvement=improvement,
            fitness_before=fitness_before,
            fitness_after=fitness_after,
            gradient_norm=grad_norm,
            parameters=dict(self._params),
            gradient=dict(gradient),
            velocity=dict(self._velocity),
            details=f"lr={self._lr:.6f}, grad_norm={grad_norm:.4f}",
        )

    def _evaluate(self, context: str, evaluate_fn: Optional[Callable]) -> float:
        if evaluate_fn:
            try:
                result = evaluate_fn(context, self._params)
                if isinstance(result, (int, float)):
                    return float(result)
                if isinstance(result, dict):
                    return float(result.get("fitness", result.get("score", 0.0)))
            except Exception as e:
                logger.warning("GEPA fitness evaluation failed: %s", e)
        return self._heuristic_fitness()

    def _evaluate_params(self, context: str, params: Dict[str, float],
                         evaluate_fn: Optional[Callable]) -> float:
        """Evaluate a specific parameter set (for PBT population)."""
        if evaluate_fn:
            try:
                result = evaluate_fn(context, params)
                if isinstance(result, (int, float)):
                    return float(result)
                if isinstance(result, dict):
                    return float(result.get("fitness", result.get("score", 0.0)))
            except Exception as e:
                logger.warning("GEPA population fitness evaluation failed: %s", e)
        # Fallback: heuristic based on params
        score = 0.0
        for name, val in params.items():
            lo, hi = self._param_ranges.get(name, (0, 1))
            normalized = (val - lo) / max(hi - lo, 1e-10)
            score += math.exp(-2.0 * (normalized - 0.5) ** 2)
        return score / max(len(params), 1)

    def _heuristic_fitness(self) -> float:
        score = 0.0
        for name, val in self._params.items():
            lo, hi = self._param_ranges[name]
            normalized = (val - lo) / max(hi - lo, 1e-10)
            score += math.exp(-2.0 * (normalized - 0.5) ** 2)
        if len(self._fitness_history) >= 3:
            recent = self._fitness_history[-3:]
            recent_std = math.sqrt(sum((x - sum(recent) / 3) ** 2 for x in recent) / 3)
            score += recent_std * 0.1
        return score / len(self._params)

    def _compute_gradient(self, context: str, evaluate_fn: Optional[Callable]) -> Dict[str, float]:
        gradient = {}
        base_params = dict(self._params)
        for name in self._params:
            lo, hi = self._param_ranges[name]
            self._params[name] = min(hi, base_params[name] + self._epsilon)
            f_plus = self._evaluate(context, evaluate_fn)
            self._params[name] = max(lo, base_params[name] - self._epsilon)
            f_minus = self._evaluate(context, evaluate_fn)
            delta = 2.0 * self._epsilon
            gradient[name] = (f_plus - f_minus) / delta
            self._params[name] = base_params[name]
        return gradient

    def _gradient_norm(self, gradient: Dict[str, float]) -> float:
        return math.sqrt(sum(v ** 2 for v in gradient.values()))

    def get_optimal_params(self) -> Dict[str, float]:
        return dict(self._best_params)

    def set_params(self, params: Dict[str, float]) -> None:
        for name, val in params.items():
            if name in self._params:
                lo, hi = self._param_ranges[name]
                self._params[name] = max(lo, min(hi, float(val)))

    def get_convergence_curve(self) -> List[float]:
        return list(self._fitness_history)

    def get_gradient_history(self, last_n: int = 50) -> List[GradientRecord]:
        return self._history[-last_n:]

    def get_stats(self) -> Dict[str, Any]:
        if not self._fitness_history:
            return {"rounds": 0, "method": self._method}

        recent = self._fitness_history[-50:] if len(self._fitness_history) >= 50 else self._fitness_history
        stats = {
            "rounds": self._round,
            "method": self._method,
            "best_fitness": self._best_fitness,
            "current_fitness": self._fitness_history[-1] if self._fitness_history else 0.0,
            "avg_recent_fitness": sum(recent) / len(recent),
            "params_count": len(self._params),
        }

        if self._method == "pbt":
            stats["population_size"] = len(self._population)
            stats["population_fitness_avg"] = (
                sum(self._population_fitness) / max(len(self._population_fitness), 1)
                if self._population_fitness else 0
            )
        else:
            stats["current_lr"] = self._lr
            stats["consecutive_no_improve"] = self._consecutive_no_improve
            stats["gradient_magnitude"] = self._gradient_norm(self._velocity)

        return stats


# Backward compatibility alias (for existing life.py imports)
GEPA = GradientEnhancedParameterAdaptation
