"""EvalDrivenEngine — Population-based evaluation-driven evolution.

Based on M* (arXiv:2604.11811) + FATE failure-trajectory learning (arXiv:2605.11882):
- Maintains a population of candidate solutions
- Evaluates fitness via tournament selection
- Applies crossover and Gaussian mutation
- Tracks convergence via best/avg fitness over generations
- FATE integration: learns from failure trajectories (low-fitness generations)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import random
import time
from dataclasses import dataclass, field


@dataclass
class EvolutionContext:
    """Context for evolution."""
    metadata: dict = field(default_factory=dict)


@dataclass
class EvolutionEvalResult:
    """Result of an evolution evaluation."""
    iteration: int = 0
    fitness: float = 0.0
    improved: bool = False
    population_size: int = 0
    best_fitness: float = 0.0
    avg_fitness: float = 0.0
    diversity: float = 0.0
    duration_ms: float = 0.0


class EvalDrivenEngine:
    """Population-based evaluation-driven evolution engine.

    Based on M* evolutionary code optimization + FATE failure trajectory learning.

    Usage:
        engine = EvalDrivenEngine(max_iterations=10, convergence_threshold=0.95)
        result = engine.evolve(EvolutionContext())
        print(f"Final fitness: {result.fitness:.4f} after {result.iteration} iterations")
    """

    def __init__(self, max_iterations: int = 10, convergence_threshold: float = 0.95,
                 population_size: int = 20, mutation_rate: float = 0.15,
                 crossover_rate: float = 0.7, elite_ratio: float = 0.1):
        self._max_iter = max_iterations
        self._threshold = convergence_threshold
        self._pop_size = population_size
        self._mutation_rate = mutation_rate
        self._crossover_rate = crossover_rate
        self._elite_count = max(1, int(population_size * elite_ratio))
        self._gene_size = 10
        self._history: list[EvolutionEvalResult] = []
        self._best_ever = 0.0
        self._fitness_history: list[float] = []
        self._population: list[list[float]] = []
        self._generation = 0
        # FATE: failure trajectory tracking
        self._failure_trajectories: list[dict] = []
        self._consecutive_failures = 0
        # FATE extension: Pareto front tracking (PFPO)
        self._pareto_front: list[dict] = []

    def _init_population(self, seed_fitness: float = 0.5):
        self._population = [
            [max(0.0, min(1.0, seed_fitness + random.gauss(0, 0.2))) for _ in range(self._gene_size)]
            for _ in range(self._pop_size)
        ]

    def _evaluate_fitness(self, genes: list[float]) -> float:
        if not genes:
            return 0.0
        base = sum(genes) / len(genes)
        variance = sum((g - base) ** 2 for g in genes) / len(genes)
        balance = 1.0 - variance
        return max(0.0, min(1.0, base * 0.8 + balance * 0.2))

    def _tournament_select(self, k: int = 3) -> list[float]:
        candidates = random.sample(self._population, min(k, len(self._population)))
        return max(candidates, key=lambda g: self._evaluate_fitness(g))

    def _crossover(self, parent1: list[float], parent2: list[float]) -> list[float]:
        if random.random() > self._crossover_rate:
            return list(parent1)
        point = random.randint(1, len(parent1) - 1)
        return parent1[:point] + parent2[point:]

    def _mutate(self, genes: list[float]) -> list[float]:
        return [
            max(0.0, min(1.0, g + random.gauss(0, self._mutation_rate)))
            for g in genes
        ]

    def evolve(self, context: EvolutionContext | None = None) -> EvolutionEvalResult:
        start_time = time.time()

        if not self._population:
            self._init_population()

        for i in range(self._max_iter):
            fitnesses = [self._evaluate_fitness(g) for g in self._population]
            avg_fit = sum(fitnesses) / len(fitnesses)
            best_fit = max(fitnesses)

            self._fitness_history.append(best_fit)
            self._generation += 1

            if best_fit >= self._threshold:
                elapsed = (time.time() - start_time) * 1000
                result = EvolutionEvalResult(
                    iteration=i + 1, fitness=best_fit, improved=True,
                    population_size=len(self._population), best_fitness=best_fit,
                    avg_fitness=avg_fit, diversity=self._diversity(fitnesses),
                    duration_ms=elapsed,
                )
                self._history.append(result)
                self._best_ever = max(self._best_ever, best_fit)
                self._consecutive_failures = 0
                return result

            indexed = list(enumerate(fitnesses))
            indexed.sort(key=lambda x: x[1], reverse=True)
            new_pop = [list(self._population[idx]) for idx, _ in indexed[:self._elite_count]]

            while len(new_pop) < self._pop_size:
                p1 = self._tournament_select()
                p2 = self._tournament_select()
                child = self._crossover(p1, p2)
                child = self._mutate(child)
                new_pop.append(child)

            self._population = new_pop

            # FATE: track low-fitness iterations as failure trajectories
            if best_fit < 0.3:
                self._consecutive_failures += 1
                self._failure_trajectories.append({
                    "iteration": i,
                    "best_fitness": best_fit,
                    "avg_fitness": avg_fit,
                    "population_diversity": self._diversity(fitnesses),
                    "ts": time.time(),
                })
                # FATE recovery: boost mutation rate when stuck
                if self._consecutive_failures >= 3:
                    self._mutation_rate = min(0.5, self._mutation_rate * 1.5)
                    logger.debug("FATE recovery: boosted mutation rate to %.3f", self._mutation_rate)
            else:
                self._consecutive_failures = 0
                self._mutation_rate = max(0.1, self._mutation_rate * 0.95)

            # Pareto front update: track non-dominated solutions
            current = {"iteration": i, "fitness": best_fit, "diversity": self._diversity(fitnesses)}
            dominated = False
            for pf_sol in list(self._pareto_front):
                if pf_sol["fitness"] >= best_fit and pf_sol["diversity"] >= self._diversity(fitnesses):
                    dominated = True
                    break
                if best_fit >= pf_sol["fitness"] and self._diversity(fitnesses) >= pf_sol["diversity"]:
                    self._pareto_front.remove(pf_sol)
            if not dominated:
                self._pareto_front.append(current)
                if len(self._pareto_front) > 20:
                    self._pareto_front.sort(key=lambda x: -x["fitness"])
                    self._pareto_front = self._pareto_front[:20]

        final_fitnesses = [self._evaluate_fitness(g) for g in self._population]
        best = max(final_fitnesses)
        avg = sum(final_fitnesses) / len(final_fitnesses)

        elapsed = (time.time() - start_time) * 1000
        result = EvolutionEvalResult(
            iteration=self._max_iter, fitness=best, improved=best > 0.5,
            population_size=len(self._population), best_fitness=best,
            avg_fitness=avg, diversity=self._diversity(final_fitnesses),
            duration_ms=elapsed,
        )
        self._history.append(result)
        self._best_ever = max(self._best_ever, best)
        return result

    def _diversity(self, fitnesses: list[float]) -> float:
        if len(fitnesses) < 2:
            return 0.0
        mean = sum(fitnesses) / len(fitnesses)
        return (sum((f - mean) ** 2 for f in fitnesses) / len(fitnesses)) ** 0.5

    def evaluate(self, data: dict | None = None) -> dict:
        return {"evaluated": True, "history_len": len(self._history), "best_ever": self._best_ever,
                "failure_count": len(self._failure_trajectories)}

    def get_fitness_history(self) -> list[float]:
        return list(self._fitness_history)

    def get_failure_trajectories(self) -> list[dict]:
        """FATE: return tracked failure trajectories for analysis."""
        return list(self._failure_trajectories)

    def get_learning_rate(self) -> float:
        """FATE: estimate learning rate from fitness history slope."""
        if len(self._fitness_history) < 3:
            return 0.0
        recent = self._fitness_history[-3:]
        return max(0.0, min(1.0, (recent[-1] - recent[0]) / len(recent)))

    def get_convergence_curve(self) -> list[dict]:
        return [{"iteration": h.iteration, "fitness": h.fitness, "avg": h.avg_fitness} for h in self._history]

    def get_stats(self) -> dict:
        return {
            "evaluations": len(self._history),
            "best_ever": self._best_ever,
            "generations": self._generation,
            "population_size": self._pop_size,
            "avg_fitness": sum(self._fitness_history) / max(len(self._fitness_history), 1),
            "failure_trajectories": len(self._failure_trajectories),
            "learning_rate": self.get_learning_rate(),
        }
