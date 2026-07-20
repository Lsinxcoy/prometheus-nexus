"""OpenSpaceEvolution — Open-space exploration with Niching and fitness landscape analysis.

Implements speciation via fitness sharing to maintain population diversity
during evolutionary optimization. Fitness sharing penalizes crowded regions
of the search space, encouraging the formation of multiple niches/species.

Key Concepts:
    1. Niching: maintain diversity through speciation/sub-populations
    2. Fitness sharing: penalize crowded regions of search space
    3. Fitness landscape: track fitness distribution, peaks, valleys
    4. Adaptive niche radius: adjust based on population diversity

References:
    - Goldberg & Richardson "Genetic algorithms with sharing for multimodal
      function optimization" (1987, ICGA)
    - Deb & Goldberg "An investigation of niche and species formation in
      genetic function optimization" (1989, ICGA)
    - Mahfoud "Niching methods for genetic algorithms" (1995, IlliGAL report)

Algorithm (Fitness Sharing):
    for each individual i:
        m_i = sum(shared(i, j) for j in population)
        f_shared[i] = f_i / m_i
    # shared(i,j) = max(0, 1 - d(i,j)/d_niche)^sigma

Complexity: O(N^2) per generation for sharing calculation
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
class Individual:
    """An individual in the evolution population."""
    individual_id: str = ""
    genes: Dict[str, float] = field(default_factory=dict)
    fitness: float = 0.0
    shared_fitness: float = 0.0
    niche_id: str = ""
    age: int = 0
    generation: int = 0


@dataclass
class NicheInfo:
    """Information about a niche/species."""
    niche_id: str = ""
    members: List[str] = field(default_factory=list)
    avg_fitness: float = 0.0
    diversity: float = 0.0
    peak_fitness: float = 0.0
    formed_generation: int = 0


@dataclass
class OpenSpaceResult:
    """Result of open-space evolution."""
    method: str = "openspace"
    best_fitness: float = 0.0
    best_genes: Dict[str, float] = field(default_factory=dict)
    num_niches: int = 0
    niches: List[NicheInfo] = field(default_factory=list)
    population_diversity: float = 0.0
    fitness_variance: float = 0.0
    generation: int = 0
    details: str = ""


class OpenSpaceEvolution:
    """Open-space exploration with niching and fitness landscape tracking.

    Implements speciation via fitness sharing, maintains multiple niches
    for diversity, tracks fitness landscape statistics over generations.

    Usage:
        os = OpenSpaceEvolution(population_size=50, gene_ranges={...})
        result = os.evolve(context="optimize", generations=10)
    """

    def __init__(self, population_size: int = 50, gene_ranges: Optional[Dict[str, Tuple[float, float]]] = None,
                 niche_radius: float = 1.0, sigma: int = 2,
                 mutation_rate: float = 0.1, mutation_strength: float = 0.05,
                 crossover_rate: float = 0.7, elite_count: int = 2,
                 evaluate_fn: Optional[Callable] = None):
        """Initialize open-space evolution.

        Args:
            population_size: Number of individuals per generation.
            gene_ranges: Dict of gene_name -> (min, max).
            niche_radius: Distance threshold for niche membership.
            sigma: Sharing function exponent.
            mutation_rate: Probability of gene mutation.
            mutation_strength: Gaussian mutation std dev.
            crossover_rate: Probability of crossover.
            elite_count: Number of elite individuals to preserve.
            evaluate_fn: Fitness evaluation function.
        """
        self._pop_size = population_size
        self._gene_ranges = gene_ranges or self._default_gene_ranges()
        self._niche_radius = niche_radius
        self._sigma = sigma
        self._mutation_rate = mutation_rate
        self._mutation_strength = mutation_strength
        self._crossover_rate = crossover_rate
        self._elite_count = elite_count
        self._evaluate_fn = evaluate_fn

        # Population state
        self._population: List[Individual] = []
        self._niches: Dict[str, NicheInfo] = {}
        self._generation = 0

        # Fitness landscape tracking
        self._fitness_history: List[float] = []
        self._peak_history: List[float] = []
        self._diversity_history: List[float] = []

    @staticmethod
    def _default_gene_ranges() -> Dict[str, Tuple[float, float]]:
        """Default gene ranges."""
        return {
            "exploration_rate": (0.01, 0.5),
            "learning_rate": (0.001, 0.1),
            "temperature": (0.1, 1.0),
            "memory_weight": (0.1, 0.9),
            "stability_factor": (0.5, 1.0),
        }

    def evolve(self, context: str = "", generations: int = 5,
               evaluate_fn: Optional[Callable] = None, **kwargs) -> OpenSpaceResult:
        """Run open-space evolution for specified generations.

        Args:
            context: Task context.
            generations: Number of generations to evolve.
            evaluate_fn: Override evaluation function.
            **kwargs: Additional parameters (current_fitness, etc.) — ignored.

        Returns:
            OpenSpaceResult with best individual and niche info.
        """
        eval_fn = evaluate_fn or self._evaluate_fn

        # Initialize population if needed
        if not self._population:
            self._population = self._initialize_population()

        for gen in range(generations):
            self._generation += 1

            # Evaluate fitness
            for ind in self._population:
                ind.fitness = self._evaluate(ind, context, eval_fn)
                ind.generation = self._generation

            # Track fitness landscape
            fitnesses = [ind.fitness for ind in self._population]
            avg_fitness = sum(fitnesses) / len(fitnesses)
            peak_fitness = max(fitnesses)
            diversity = self._compute_diversity()

            self._fitness_history.append(avg_fitness)
            self._peak_history.append(peak_fitness)
            self._diversity_history.append(diversity)

            # Niching: compute fitness sharing
            self._assign_niches()
            self._compute_shared_fitness()

            # Selection + reproduction
            self._reproduce()

        # Final result
        best = max(self._population, key=lambda i: i.fitness)
        niches_info = list(self._niches.values())

        return OpenSpaceResult(
            method="openspace",
            best_fitness=best.fitness,
            best_genes=dict(best.genes),
            num_niches=len(niches_info),
            niches=niches_info,
            population_diversity=self._compute_diversity(),
            fitness_variance=sum((f - avg_fitness) ** 2 for f in fitnesses) / len(fitnesses),
            generation=self._generation,
            details=f"niches={len(niches_info)}, diversity={diversity:.4f}",
        )

    def _initialize_population(self) -> List[Individual]:
        """Initialize population with random individuals."""
        population = []
        for i in range(self._pop_size):
            genes = {}
            for name, (lo, hi) in self._gene_ranges.items():
                genes[name] = random.uniform(lo, hi)
            ind = Individual(
                individual_id=f"ind_{self._generation}_{i}",
                genes=genes,
                age=0,
                generation=self._generation,
            )
            population.append(ind)
        return population

    def _evaluate(self, individual: Individual, context: str,
                  evaluate_fn: Optional[Callable]) -> float:
        """Evaluate individual fitness."""
        if evaluate_fn:
            try:
                result = evaluate_fn(context, individual.genes)
                if isinstance(result, (int, float)):
                    return float(result)
                if isinstance(result, dict):
                    return float(result.get("fitness", result.get("score", 0.0)))
            except Exception as e:
                logger.warning("OpenSpace fitness evaluation failed: %s", e)
        # Heuristic fitness
        score = 0.0
        for name, val in individual.genes.items():
            lo, hi = self._gene_ranges[name]
            normalized = (val - lo) / max(hi - lo, 1e-10)
            score += math.exp(-2.0 * (normalized - 0.5) ** 2)
        return score / len(self._gene_ranges)

    def _assign_niches(self) -> None:
        """Assign individuals to niches using clustering."""
        self._niches = {}
        niche_counter = 0

        for ind in self._population:
            assigned = False
            # Try to fit into existing niche
            for niche_id, niche in list(self._niches.items()):
                # Check distance to niche centroid
                centroid = self._compute_centroid(niche.members)
                if centroid:
                    dist = self._distance(ind.genes, centroid)
                    if dist <= self._niche_radius:
                        niche.members.append(ind.individual_id)
                        ind.niche_id = niche_id
                        assigned = True
                        break

            if not assigned:
                # Create new niche
                niche_id = f"niche_{niche_counter}"
                self._niches[niche_id] = NicheInfo(
                    niche_id=niche_id,
                    members=[ind.individual_id],
                    formed_generation=self._generation,
                )
                ind.niche_id = niche_id
                niche_counter += 1

        # Update niche stats
        for niche in self._niches.values():
            members = [i for i in self._population if i.individual_id in niche.members]
            if members:
                niche.avg_fitness = sum(m.fitness for m in members) / len(members)
                niche.peak_fitness = max(m.fitness for m in members)
                niche.diversity = self._compute_niche_diversity(members)

    def _compute_shared_fitness(self) -> None:
        """Compute fitness sharing: penalize crowded niches."""
        for ind in self._population:
            sharing_count = 0.0
            for other in self._population:
                dist = self._distance(ind.genes, other.genes)
                sharing_count += max(0, 1 - dist / self._niche_radius) ** self._sigma
            ind.shared_fitness = ind.fitness / max(sharing_count, 1.0)

    def _reproduce(self) -> None:
        """Selection + crossover + mutation."""
        # Tournament selection with shared fitness
        selected = []
        for _ in range(self._pop_size):
            # Tournament of 3
            candidates = random.sample(self._population, min(3, len(self._population)))
            winner = max(candidates, key=lambda i: i.shared_fitness)
            selected.append(winner)

        # Elitism: preserve best individuals
        elites = sorted(self._population, key=lambda i: -i.fitness)[:self._elite_count]

        # Crossover + mutation
        new_population = list(elites)
        i = 0
        while len(new_population) < self._pop_size and i < len(selected) - 1:
            parent1, parent2 = selected[i], selected[i + 1]

            if random.random() < self._crossover_rate:
                child_genes = self._crossover(parent1.genes, parent2.genes)
            else:
                child_genes = dict(parent1.genes)

            # Mutation
            child_genes = self._mutate(child_genes)

            # Clip to bounds
            for name in child_genes:
                if name in self._gene_ranges:
                    lo, hi = self._gene_ranges[name]
                    child_genes[name] = max(lo, min(hi, child_genes[name]))

            child = Individual(
                individual_id=f"ind_{self._generation + 1}_{len(new_population)}",
                genes=child_genes,
                age=0,
                generation=self._generation + 1,
            )
            new_population.append(child)
            i += 2

        self._population = new_population

    def _crossover(self, genes1: Dict[str, float],
                   genes2: Dict[str, float]) -> Dict[str, float]:
        """Blend crossover: linear combination of parents."""
        child = {}
        alpha = random.random()
        for name in genes1:
            child[name] = alpha * genes1[name] + (1 - alpha) * genes2.get(name, genes1[name])
        return child

    def _mutate(self, genes: Dict[str, float]) -> Dict[str, float]:
        """Gaussian mutation."""
        mutated = dict(genes)
        for name in mutated:
            if random.random() < self._mutation_rate:
                mutated[name] += random.gauss(0, self._mutation_strength)
        return mutated

    def _distance(self, genes1: Dict[str, float],
                  genes2: Dict[str, float]) -> float:
        """Euclidean distance between gene vectors."""
        sum_sq = 0.0
        count = 0
        for name in genes1:
            if name in genes2:
                sum_sq += (genes1[name] - genes2[name]) ** 2
                count += 1
        return math.sqrt(sum_sq / max(count, 1))

    def _compute_centroid(self, member_ids: List[str]) -> Optional[Dict[str, float]]:
        """Compute centroid of niche members."""
        members = [i for i in self._population if i.individual_id in member_ids]
        if not members:
            return None
        centroid = {}
        for name in self._gene_ranges:
            centroid[name] = sum(i.genes.get(name, 0) for i in members) / len(members)
        return centroid

    def _compute_diversity(self) -> float:
        """Compute population diversity (avg pairwise distance)."""
        if len(self._population) < 2:
            return 0.0
        # Sample pairs for efficiency
        sample_size = min(20, len(self._population))
        sample = random.sample(self._population, sample_size)
        total_dist = 0.0
        pairs = 0
        for i in range(len(sample)):
            for j in range(i + 1, len(sample)):
                total_dist += self._distance(sample[i].genes, sample[j].genes)
                pairs += 1
        return total_dist / max(pairs, 1)

    def _compute_niche_diversity(self, members: List[Individual]) -> float:
        """Compute diversity within a niche."""
        if len(members) < 2:
            return 0.0
        total_dist = 0.0
        pairs = 0
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                total_dist += self._distance(members[i].genes, members[j].genes)
                pairs += 1
        return total_dist / max(pairs, 1)

    def get_fitness_landscape(self) -> Dict[str, Any]:
        """Get fitness landscape statistics."""
        return {
            "fitness_history": self._fitness_history[-100:],
            "peak_history": self._peak_history[-100:],
            "diversity_history": self._diversity_history[-100:],
            "current_avg": self._fitness_history[-1] if self._fitness_history else 0.0,
            "current_peak": self._peak_history[-1] if self._peak_history else 0.0,
            "current_diversity": self._diversity_history[-1] if self._diversity_history else 0.0,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get OpenSpace statistics."""
        return {
            "generation": self._generation,
            "population_size": len(self._population),
            "num_niches": len(self._niches),
            "diversity": self._compute_diversity(),
            "fitness_landscape": self.get_fitness_landscape(),
        }


# Backward compatibility alias (for existing life.py imports)
OpenSpace = OpenSpaceEvolution
