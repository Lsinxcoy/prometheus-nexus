"""EvolutionEngine — 12-layer genetic algorithm engine.

Based on: Legacy Omega engine.py (366 lines, 12-layer GA)
Implements full genetic algorithm with 12 distinct layers:
    1. Chromosome — top-level container with fitness
    2. GeneContainer — organizes genes into groups
    3. Gene — individual parameter with type/bounds
    4. Mutation — multiple mutation strategies
    5. Crossover — multiple crossover operators
    6. Selection — tournament, roulette, rank selection
    7. Elitism — preserve best individuals
    8. Diversity — niching/speciation tracking
    9. Archive — hall of fame, pareto front
    10. Controller — adaptive parameters
    11. Terminator — convergence detection
    12. Evaluator — fitness computation pipeline

Key Concepts:
    1. Chromosome → GeneContainer → Gene hierarchy
    2. Multiple mutation strategies (Gaussian, uniform, inversion, swap)
    3. Multiple crossover operators (single-point, multi-point, uniform, blend)
    4. Adaptive mutation rate based on population diversity
    5. Hall of fame tracking best individuals ever

Algorithm:
    for generation in range(max_generations):
        evaluate(population)
        archive.update(population)
        if terminator.check(population): break
        controller.adapt(population)
        parents = selection.select(population)
        offspring = []
        for p1, p2 in pairs(parents):
            child = crossover.apply(p1, p2)
            child = mutation.apply(child)
            offspring.append(child)
        population = elitism.combine(population, offspring)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import math
import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


# === Layer 3: Gene ===
@dataclass
class Gene:
    """Individual gene with type, bounds, and value."""
    gene_id: str = ""
    name: str = ""
    value: float = 0.0
    min_val: float = 0.0
    max_val: float = 1.0
    gene_type: str = "float"  # float, int, categorical
    categories: List[str] = field(default_factory=list)
    weight: float = 1.0  # Importance weight for fitness


# === Layer 2: GeneContainer ===
@dataclass
class GeneContainer:
    """Container for a group of related genes."""
    container_id: str = ""
    name: str = ""
    genes: List[Gene] = field(default_factory=list)
    weight: float = 1.0  # Group weight


# === Layer 1: Chromosome ===
@dataclass
class Chromosome:
    """Top-level chromosome with containers and fitness."""
    chromosome_id: str = ""
    containers: List[GeneContainer] = field(default_factory=list)
    fitness: float = 0.0
    age: int = 0
    generation: int = 0
    parent_ids: List[str] = field(default_factory=list)
    tags: Dict[str, Any] = field(default_factory=dict)


class MutationStrategy(Enum):
    GAUSSIAN = "gaussian"
    UNIFORM = "uniform"
    INVERSION = "inversion"
    SWAP = "swap"
    POWER = "power"  # Power-law mutation


class CrossoverOperator(Enum):
    SINGLE_POINT = "single_point"
    MULTI_POINT = "multi_point"
    UNIFORM = "uniform"
    BLEND = "blend"  # BLX-α blend crossover
    ARITHMETIC = "arithmetic"


class SelectionMethod(Enum):
    TOURNAMENT = "tournament"
    ROULETTE = "roulette"
    RANK = "rank"
    TRUNCATION = "truncation"
    STOHASTIC_UNIVERSAL = "sus"


# === Layer 4: Mutation ===
class MutationEngine:
    """Multiple mutation strategies."""

    @staticmethod
    def mutate(chromosome: Chromosome, strategy: MutationStrategy = MutationStrategy.GAUSSIAN,
               rate: float = 0.1, strength: float = 0.1) -> Chromosome:
        """Apply mutation to chromosome."""
        for container in chromosome.containers:
            for gene in container.genes:
                if random.random() < rate:
                    if strategy == MutationStrategy.GAUSSIAN:
                        gene.value += random.gauss(0, strength * (gene.max_val - gene.min_val))
                    elif strategy == MutationStrategy.UNIFORM:
                        gene.value = random.uniform(gene.min_val, gene.max_val)
                    elif strategy == MutationStrategy.INVERSION:
                        mid = (gene.min_val + gene.max_val) / 2
                        gene.value = 2 * mid - gene.value
                    elif strategy == MutationStrategy.SWAP:
                        # Swap toward best or random
                        gene.value = random.choice([gene.min_val, gene.max_val, gene.value])
                    elif strategy == MutationStrategy.POWER:
                        delta = (gene.max_val - gene.min_val) * random.random() ** 2
                        gene.value += random.choice([-1, 1]) * delta
                    # Clip
                    gene.value = max(gene.min_val, min(gene.max_val, gene.value))
                    if gene.gene_type == "int":
                        gene.value = round(gene.value)
        return chromosome


# === Layer 5: Crossover ===
class CrossoverEngine:
    """Multiple crossover operators."""

    @staticmethod
    def crossover(parent1: Chromosome, parent2: Chromosome,
                  operator: CrossoverOperator = CrossoverOperator.SINGLE_POINT,
                  alpha: float = 0.5) -> Tuple[Chromosome, Chromosome]:
        """Perform crossover between two parents."""
        # Flatten genes for crossover
        genes1 = CrossoverEngine._flatten(parent1)
        genes2 = CrossoverEngine._flatten(parent2)

        if operator == CrossoverOperator.SINGLE_POINT:
            return CrossoverEngine._single_point(genes1, genes2, parent1, parent2)
        elif operator == CrossoverOperator.MULTI_POINT:
            return CrossoverEngine._multi_point(genes1, genes2, parent1, parent2)
        elif operator == CrossoverOperator.UNIFORM:
            return CrossoverEngine._uniform(genes1, genes2, parent1, parent2)
        elif operator == CrossoverOperator.BLEND:
            return CrossoverEngine._blend(genes1, genes2, alpha, parent1, parent2)
        elif operator == CrossoverOperator.ARITHMETIC:
            return CrossoverEngine._arithmetic(genes1, genes2, alpha, parent1, parent2)
        else:
            return CrossoverEngine._single_point(genes1, genes2, parent1, parent2)

    @staticmethod
    def _single_point(g1: List[Gene], g2: List[Gene],
                      p1: Chromosome, p2: Chromosome) -> Tuple[Chromosome, Chromosome]:
        if not g1:
            return Chromosome(), Chromosome()
        if len(g1) < 2:
            # Single-gene chromosome: no cut point possible — return copies of parents
            return CrossoverEngine._build_chromosome(list(g1), p1, p2), \
                   CrossoverEngine._build_chromosome(list(g2), p2, p1)
        point = random.randint(1, len(g1) - 1)
        child1_genes = g1[:point] + [Gene(gene_id=g.gene_id, name=g.name, value=g2[i].value,
                                          min_val=g2[i].min_val, max_val=g2[i].max_val)
                                      for i, g in enumerate(g1[point:])]
        child2_genes = g2[:point] + [Gene(gene_id=g.gene_id, name=g.name, value=g1[i].value,
                                          min_val=g1[i].min_val, max_val=g1[i].max_val)
                                      for i, g in enumerate(g2[point:])]
        return CrossoverEngine._build_chromosome(child1_genes, p1, p2), \
               CrossoverEngine._build_chromosome(child2_genes, p2, p1)

    @staticmethod
    def _multi_point(g1: List[Gene], g2: List[Gene],
                     p1: Chromosome, p2: Chromosome) -> Tuple[Chromosome, Chromosome]:
        n = len(g1)
        if n < 3:
            # Not enough genes for multiple cut points — fall back to single point
            return CrossoverEngine._single_point(g1, g2, p1, p2)
        n_points = random.randint(2, min(4, n - 1))
        points = sorted(random.sample(range(1, n), n_points))
        child1_genes = []
        child2_genes = []
        use_g1 = True
        for i, (a, b) in enumerate(zip(g1, g2)):
            if i in points:
                use_g1 = not use_g1
            child1_genes.append(Gene(gene_id=a.gene_id, name=a.name,
                                     value=a.value if use_g1 else b.value,
                                     min_val=a.min_val, max_val=a.max_val))
            child2_genes.append(Gene(gene_id=a.gene_id, name=a.name,
                                     value=b.value if use_g1 else a.value,
                                     min_val=b.min_val, max_val=b.max_val))
        return CrossoverEngine._build_chromosome(child1_genes, p1, p2), \
               CrossoverEngine._build_chromosome(child2_genes, p2, p1)

    @staticmethod
    def _uniform(g1: List[Gene], g2: List[Gene],
                 p1: Chromosome, p2: Chromosome) -> Tuple[Chromosome, Chromosome]:
        child1_genes = []
        child2_genes = []
        for a, b in zip(g1, g2):
            if random.random() < 0.5:
                child1_genes.append(Gene(gene_id=a.gene_id, name=a.name, value=a.value,
                                         min_val=a.min_val, max_val=a.max_val))
                child2_genes.append(Gene(gene_id=b.gene_id, name=b.name, value=b.value,
                                         min_val=b.min_val, max_val=b.max_val))
            else:
                child1_genes.append(Gene(gene_id=a.gene_id, name=a.name, value=b.value,
                                         min_val=a.min_val, max_val=a.max_val))
                child2_genes.append(Gene(gene_id=b.gene_id, name=b.name, value=a.value,
                                         min_val=b.min_val, max_val=b.max_val))
        return CrossoverEngine._build_chromosome(child1_genes, p1, p2), \
               CrossoverEngine._build_chromosome(child2_genes, p2, p1)

    @staticmethod
    def _blend(g1: List[Gene], g2: List[Gene], alpha: float,
               p1: Chromosome, p2: Chromosome) -> Tuple[Chromosome, Chromosome]:
        """BLX-α blend crossover: extend range by α, sample uniformly."""
        child1_genes = []
        child2_genes = []
        for a, b in zip(g1, g2):
            mn = min(a.value, b.value)
            mx = max(a.value, b.value)
            ext = (mx - mn) * alpha
            p_min = max(a.min_val, mn - ext)
            p_max = min(a.max_val, mx + ext)
            v1 = random.uniform(p_min, p_max)
            v2 = random.uniform(p_min, p_max)
            child1_genes.append(Gene(gene_id=a.gene_id, name=a.name, value=v1,
                                     min_val=a.min_val, max_val=a.max_val))
            child2_genes.append(Gene(gene_id=b.gene_id, name=b.name, value=v2,
                                     min_val=b.min_val, max_val=b.max_val))
        return CrossoverEngine._build_chromosome(child1_genes, p1, p2), \
               CrossoverEngine._build_chromosome(child2_genes, p2, p1)

    @staticmethod
    def _arithmetic(g1: List[Gene], g2: List[Gene], alpha: float,
                    p1: Chromosome, p2: Chromosome) -> Tuple[Chromosome, Chromosome]:
        child1_genes = []
        child2_genes = []
        for a, b in zip(g1, g2):
            v1 = alpha * a.value + (1 - alpha) * b.value
            v2 = (1 - alpha) * a.value + alpha * b.value
            child1_genes.append(Gene(gene_id=a.gene_id, name=a.name, value=v1,
                                     min_val=a.min_val, max_val=a.max_val))
            child2_genes.append(Gene(gene_id=b.gene_id, name=b.name, value=v2,
                                     min_val=b.min_val, max_val=b.max_val))
        return CrossoverEngine._build_chromosome(child1_genes, p1, p2), \
               CrossoverEngine._build_chromosome(child2_genes, p2, p1)

    @staticmethod
    def _flatten(chromosome: Chromosome) -> List[Gene]:
        """Flatten all genes from all containers."""
        genes = []
        for container in chromosome.containers:
            genes.extend(container.genes)
        return genes

    @staticmethod
    def _build_chromosome(genes: List[Gene], parent1: Chromosome,
                          parent2: Chromosome) -> Chromosome:
        """Build chromosome from flat gene list."""
        # Group genes back into containers (single container for simplicity)
        container = GeneContainer(
            container_id=str(uuid.uuid4())[:8],
            name="genes",
            genes=genes,
        )
        return Chromosome(
            chromosome_id=str(uuid.uuid4())[:8],
            containers=[container],
            parent_ids=[parent1.chromosome_id, parent2.chromosome_id],
        )


# === Layer 6: Selection ===
class SelectionEngine:
    """Multiple selection methods."""

    @staticmethod
    def select(population: List[Chromosome], method: SelectionMethod = SelectionMethod.TOURNAMENT,
               tournament_size: int = 3, truncation_ratio: float = 0.5) -> List[Chromosome]:
        """Select parents for reproduction."""
        if method == SelectionMethod.TOURNAMENT:
            return SelectionEngine._tournament(population, tournament_size)
        elif method == SelectionMethod.ROULETTE:
            return SelectionEngine._roulette(population)
        elif method == SelectionMethod.RANK:
            return SelectionEngine._rank(population)
        elif method == SelectionMethod.TRUNCATION:
            return SelectionEngine._truncation(population, truncation_ratio)
        elif method == SelectionMethod.STOHASTIC_UNIVERSAL:
            return SelectionEngine._sus(population)
        else:
            return SelectionEngine._tournament(population, tournament_size)

    @staticmethod
    def _tournament(population: List[Chromosome], size: int) -> List[Chromosome]:
        """Tournament selection: pick best of random subset."""
        selected = []
        for _ in range(len(population)):
            candidates = random.sample(population, min(size, len(population)))
            winner = max(candidates, key=lambda c: c.fitness)
            selected.append(winner)
        return selected

    @staticmethod
    def _roulette(population: List[Chromosome]) -> List[Chromosome]:
        """Roulette wheel selection proportional to fitness."""
        total_fitness = max(sum(c.fitness for c in population), 1e-10)
        probabilities = [c.fitness / total_fitness for c in population]
        selected = []
        for _ in range(len(population)):
            r = random.random()
            cumulative = 0.0
            for c, p in zip(population, probabilities):
                cumulative += p
                if r <= cumulative:
                    selected.append(c)
                    break
        return selected

    @staticmethod
    def _rank(population: List[Chromosome]) -> List[Chromosome]:
        """Rank-based selection: probability proportional to rank."""
        sorted_pop = sorted(population, key=lambda c: c.fitness)
        n = len(sorted_pop)
        selected = []
        for _ in range(n):
            # Higher rank = higher probability
            weights = list(range(1, n + 1))
            total = sum(weights)
            r = random.random() * total
            cumulative = 0.0
            for chromo, w in zip(sorted_pop, weights):
                cumulative += w
                if r <= cumulative:
                    selected.append(chromo)
                    break
        return selected

    @staticmethod
    def _truncation(population: List[Chromosome], ratio: float) -> List[Chromosome]:
        """Truncation: select top fraction, replicate to fill."""
        sorted_pop = sorted(population, key=lambda c: -c.fitness)
        top_count = max(1, int(len(sorted_pop) * ratio))
        top = sorted_pop[:top_count]
        # Replicate to fill
        selected = list(top)
        while len(selected) < len(population):
            selected.extend(top)
        return selected[:len(population)]

    @staticmethod
    def _sus(population: List[Chromosome]) -> List[Chromosome]:
        """Stochastic Universal Sampling."""
        total_fitness = max(sum(c.fitness for c in population), 1e-10)
        n = len(population)
        step = total_fitness / n
        start = random.uniform(0, step)
        selected = []
        cumulative = 0.0
        idx = 0
        for i in range(n):
            point = start + i * step
            while idx < len(population) - 1 and cumulative + population[idx].fitness < point:
                cumulative += population[idx].fitness
                idx += 1
            selected.append(population[idx])
        return selected


# === Layer 7: Elitism ===
class ElitismEngine:
    """Elitist preservation."""

    @staticmethod
    def combine(old_population: List[Chromosome], new_population: List[Chromosome],
                elite_count: int = 2) -> List[Chromosome]:
        """Combine old and new with elitism."""
        sorted_old = sorted(old_population, key=lambda c: -c.fitness)
        elites = sorted_old[:elite_count]
        offspring = new_population[elite_count:] if len(new_population) > elite_count else []
        return elites + offspring


# === Layer 8: Diversity ===
class DiversityEngine:
    """Diversity tracking and maintenance."""

    @staticmethod
    def compute(population: List[Chromosome]) -> float:
        """Compute population diversity as avg pairwise distance."""
        if len(population) < 2:
            return 0.0
        sample = random.sample(population, min(20, len(population)))
        total_dist = 0.0
        pairs = 0
        for i in range(len(sample)):
            for j in range(i + 1, len(sample)):
                dist = DiversityEngine._distance(sample[i], sample[j])
                total_dist += dist
                pairs += 1
        return total_dist / max(pairs, 1)

    @staticmethod
    def _distance(c1: Chromosome, c2: Chromosome) -> float:
        """Hamming distance between two chromosomes."""
        genes1 = CrossoverEngine._flatten(c1)
        genes2 = CrossoverEngine._flatten(c2)
        if not genes1 or not genes2:
            return 0.0
        sum_sq = 0.0
        for g1, g2 in zip(genes1, genes2):
            if g1.max_val != g1.min_val:
                norm_diff = abs(g1.value - g2.value) / (g1.max_val - g1.min_val)
            else:
                norm_diff = 0.0 if g1.value == g2.value else 1.0
            sum_sq += norm_diff ** 2
        return math.sqrt(sum_sq / max(len(genes1), 1))


# === Layer 9: Archive ===
@dataclass
class Archive:
    """Hall of fame and Pareto front."""
    hall_of_fame: List[Chromosome] = field(default_factory=list)
    pareto_front: List[Chromosome] = field(default_factory=list)
    max_hof_size: int = 10

    def update(self, population: List[Chromosome]) -> None:
        """Update hall of fame with best individuals."""
        sorted_pop = sorted(population, key=lambda c: -c.fitness)
        for chromo in sorted_pop:
            if len(self.hall_of_fame) < self.max_hof_size:
                self.hall_of_fame.append(chromo)
            elif chromo.fitness > self.hall_of_fame[-1].fitness:
                self.hall_of_fame[-1] = chromo
        # Update Pareto front (simplified: top diverse individuals)
        self.pareto_front = list(sorted_pop[:5])


# === Layer 10: Controller ===
class Controller:
    """Adaptive parameter control."""

    def __init__(self, base_mutation_rate: float = 0.1, base_strength: float = 0.1,
                 diversity_target: float = 0.5):
        self.mutation_rate = base_mutation_rate
        self.mutation_strength = base_strength
        self._base_rate = base_mutation_rate
        self._base_strength = base_strength
        self._target_diversity = diversity_target
        self._adaptation_history: List[Dict[str, float]] = []

    def adapt(self, population: List[Chromosome]) -> Dict[str, float]:
        """Adapt mutation parameters based on population diversity."""
        diversity = DiversityEngine.compute(population)

        # Adaptive mutation: increase rate when diversity is low
        if diversity < self._target_diversity * 0.5:
            self.mutation_rate = min(0.5, self._base_rate * 2)
            self.mutation_strength = min(0.3, self._base_strength * 1.5)
        elif diversity > self._target_diversity * 1.5:
            self.mutation_rate = max(0.01, self._base_rate * 0.5)
            self.mutation_strength = max(0.01, self._base_strength * 0.5)
        else:
            self.mutation_rate = self._base_rate
            self.mutation_strength = self._base_strength

        # Check for premature convergence
        if population:
            sorted_pop = sorted(population, key=lambda c: -c.fitness)
            top_10_count = max(1, len(sorted_pop) // 10)
            top_fitness = sorted_pop[:top_10_count]
            fitness_spread = max(c.fitness for c in top_fitness) - min(c.fitness for c in top_fitness)
            if fitness_spread < 0.01:
                # Premature convergence — boost mutation
                self.mutation_rate = min(0.3, self.mutation_rate * 1.5)

        params = {
            "mutation_rate": self.mutation_rate,
            "mutation_strength": self.mutation_strength,
            "diversity": diversity,
        }
        self._adaptation_history.append(params)
        if len(self._adaptation_history) > 1000:
            self._adaptation_history = self._adaptation_history[-500:]

        return params


# === Layer 11: Terminator ===
class Terminator:
    """Convergence detection and termination with diversity injection."""

    def __init__(self, max_generations: int = 100, stagnation_limit: int = 20,
                 fitness_threshold: float = 0.99, min_generations: int = 10):
        self._max_gen = max_generations
        self._stagnation = stagnation_limit
        self._threshold = fitness_threshold
        self._min_gen = min_generations  # 【P1修复】从5提高到10
        self._best_history: List[float] = []
        self._converged = False
        self._reason = ""
        # 【P1修复】多样性注入参数
        self._min_diversity_threshold = 0.3  # 低于此值触发多样性注入
        self._consecutive_stagnant = 0  # 连续停滞代数

    def check(self, population: List[Chromosome], generation: int) -> bool:
        """Check if evolution should terminate."""
        if not population:
            return True

        best = max(c.fitness for c in population)
        self._best_history.append(best)

        # Max generations
        if generation >= self._max_gen:
            self._converged = True
            self._reason = "max_generations"
            return True

        # Fitness threshold - 需要更多代数才收敛
        if best >= self._threshold and generation >= self._min_gen:
            self._converged = True
            self._reason = "threshold_reached"
            return True

        # Stagnation detection
        if len(self._best_history) >= self._stagnation:
            recent = self._best_history[-self._stagnation:]
            improvement = max(recent) - min(recent)
            if improvement < 1e-6:
                self._consecutive_stagnant += 1
                # 【P1修复】连续停滞3代以上才考虑重启
                if self._consecutive_stagnant >= 3:
                    self._converged = True
                    self._reason = "stagnation"
                    return True
            else:
                self._consecutive_stagnant = 0

        return False

    @property
    def is_converged(self) -> bool:
        return self._converged

    @property
    def convergence_reason(self) -> str:
        return self._reason

    def reset(self) -> None:
        """Reset for new evolution cycle."""
        self._converged = False
        self._reason = ""
        self._best_history.clear()
        self._consecutive_stagnant = 0


# === Layer 12: Evaluator ===
class Evaluator:
    """Fitness evaluation pipeline."""

    @staticmethod
    def evaluate(population: List[Chromosome],
                 evaluate_fn: Optional[Callable] = None,
                 context: str = "") -> None:
        """Evaluate all chromosomes in population."""
        for chromo in population:
            if evaluate_fn:
                try:
                    genes = CrossoverEngine._flatten(chromo)
                    params = {g.name: g.value for g in genes}
                    result = evaluate_fn(context, params)
                    if isinstance(result, (int, float)):
                        chromo.fitness = float(result)
                    elif isinstance(result, dict):
                        chromo.fitness = float(result.get("fitness", result.get("score", 0.0)))
                    else:
                        chromo.fitness = Evaluator._heuristic_fitness(genes)
                except Exception:
                    logger.warning("EvolutionEngine: evaluation failed, using heuristic fitness")
                    chromo.fitness = Evaluator._heuristic_fitness(genes)
            else:
                genes = CrossoverEngine._flatten(chromo)
                chromo.fitness = Evaluator._heuristic_fitness(genes)

    @staticmethod
    def _heuristic_fitness(genes: List[Gene], utility_anchor: float = 0.5) -> float:
        """Heuristic fitness: weighted sum of normalized values, 融合真实效用锚 [D3].

        D3 修复(自指漂移): 原 heuristic 只量"基因值在合法区间的居中度" -> 参数自指,
        系统可能收敛到"参数看起来优但对宿主无价值"的局部. 现融合 utility_anchor:
        - utility_anchor 来自系统真实效用信号(utility_tracker 命中/访问, 或宿主回 confirm)
        - 无锚时默认 0.5(中性, 退化为原居中启发式, 向后兼容)
        """
        if not genes:
            return 0.0
        score = 0.0
        total_weight = 0.0
        for gene in genes:
            if gene.max_val != gene.min_val:
                normalized = (gene.value - gene.min_val) / (gene.max_val - gene.min_val)
            else:
                normalized = 0.5
            # Gaussian preference for center
            gene_score = math.exp(-2.0 * (normalized - 0.5) ** 2)
            score += gene_score * gene.weight
            total_weight += gene.weight
        base = score / max(total_weight, 1e-10)
        # 融合效用锚: 真实效用高 -> fitness 上抬, 低 -> 下压(不再纯自指)
        return base * 0.6 + utility_anchor * 0.4


# === Main Evolution Engine ===
class EvolutionEngine:
    """12-layer genetic algorithm engine.

    Full GA implementation with chromosome/gene hierarchy,
    multiple mutation/crossover strategies, adaptive control,
    and convergence detection.

    Usage:
        engine = EvolutionEngine(
            gene_specs={"lr": (0.001, 0.1), "batch": (16, 512)},
            population_size=50,
            max_generations=100,
        )
        result = engine.evolve(context="optimize", evaluate_fn=my_fn)
    """

    def __init__(self, gene_specs: Optional[Dict[str, Tuple[float, float]]] = None,
                 population_size: int = 50, max_generations: int = 100,
                 elite_count: int = 2, mutation_rate: float = 0.1,
                 mutation_strength: float = 0.1, crossover_rate: float = 0.7,
                 tournament_size: int = 3, fitness_threshold: float = 0.85,  # Was 0.99 - allow more evolution
                 stagnation_limit: int = 20, evaluate_fn: Optional[Callable] = None):
        """Initialize evolution engine.

        Args:
            gene_specs: Dict of gene_name -> (min, max).
            population_size: Individuals per generation.
            max_generations: Max evolution generations.
            elite_count: Elite individuals to preserve.
            mutation_rate: Base mutation probability.
            mutation_strength: Gaussian mutation std dev.
            crossover_rate: Probability of crossover.
            tournament_size: Tournament selection size.
            fitness_threshold: Target fitness for early termination.
            stagnation_limit: Generations of no improvement before stop.
            evaluate_fn: Fitness evaluation function.
        """
        self._gene_specs = gene_specs or {}
        self._pop_size = population_size
        self._max_gen = max_generations
        self._elite_count = elite_count
        self._crossover_rate = crossover_rate
        self._tournament_size = tournament_size
        self._evaluate_fn = evaluate_fn
        # D3: 真实效用锚 — 融合进 fitness, 防止参数自指漂移. 由 Omega 注入(utility_tracker 信号)
        self._utility_anchor = 0.5

        # Layer instances
        self._controller = Controller(mutation_rate, mutation_strength)
        self._terminator = Terminator(
            max_generations=max_generations,
            stagnation_limit=stagnation_limit,
            fitness_threshold=fitness_threshold,
        )
        self._archive = Archive()

        # State
        self._population: List[Chromosome] = []
        self._generation = 0
        self._fitness_history: List[float] = []
        self._diversity_history: List[float] = []
        self._params_history: List[Dict[str, float]] = []
        self._history = self._fitness_history  # 兼容别名: state_persistence 引用

    def inject_gene_specs(self, specs: Dict[str, Tuple[float, float]]) -> int:
        """P0a: 注入外部机制提取的 gene_specs (来自 T3 GitHub 机制提取轨).

        解 B1(僵尸机制): T3 提取的机制激活后, 经此把其参数维度注入进化引擎,
        让 T3 产物真接生产(而非躺在 registry._enabled 里). 走 A-B 并行原则 —
        注入的是"候选基因维度", 由后续 evolve() 的适应度评估决定去留, 不强制覆盖.

        Args:
            specs: {gene_name: (min, max)} 新增基因维度
        Returns:
            int: 实际注入的新维度数
        """
        added = 0
        for name, (lo, hi) in specs.items():
            if name not in self._gene_specs:
                self._gene_specs[name] = (float(lo), float(hi))
                added += 1
        if added:
            logger.info("EvolutionEngine: injected %d gene specs from T3 (total=%d)", added, len(self._gene_specs))
        return added

    def set_utility_anchor(self, anchor: float) -> None:
        """D3: 设置真实效用锚(0..1). Omega 注入 utility_tracker 真实信号.
        无宿主回 confirm 时, 用系统内部真实使用度(命中/访问)作为外部锚, 防自指漂移.
        """
        self._utility_anchor = max(0.0, min(1.0, float(anchor)))

    def evolve(self, context: str = "", evaluate_fn: Optional[Callable] = None,
               gene_specs: Optional[Dict[str, Tuple[float, float]]] = None,
               max_generations: Optional[int] = None) -> Dict[str, Any]:
        """Run evolution.

        Args:
            context: Task context.
            evaluate_fn: Override evaluation function.
            gene_specs: Override gene specifications.
            max_generations: Override max generations.

        Returns:
            Dict with best chromosome, fitness history, and statistics.
        """
        specs = gene_specs or self._gene_specs or self._default_gene_specs()
        eval_fn = evaluate_fn or self._evaluate_fn
        # D3: 无外部 eval_fn 时, 用融合效用锚的启发式(防止纯参数自指)
        # utility_anchor 来自 Omega 注入的真实效用信号(utility_tracker / 宿主回 confirm)
        if eval_fn is None:
            anchor = self._utility_anchor
            def eval_fn(ctx, params):  # noqa: E306
                # 构造伪基因列表以复用 _heuristic_fitness(仅用到值/边界/权重)
                from prometheus_nexus.evolution.evolution_engine import Gene
                genes = [Gene(gene_id=n, name=n, value=v,
                              min_val=specs.get(n, (0, 1))[0],
                              max_val=specs.get(n, (0, 1))[1]) for n, v in params.items()]
                return Evaluator._heuristic_fitness(genes, utility_anchor=anchor)

        # Initialize population (仅首次/种群为空时)
        if not self._population:
            self._population = self._initialize_population(specs)

        # Use provided max_generations or default (cap at 10 to avoid long runs)
        max_gen = max_generations if max_generations is not None else min(self._max_gen, 10)
        original_max_gen = self._terminator._max_gen
        self._terminator._max_gen = max_gen

        # Evolution loop
        while not self._terminator.check(self._population, self._generation):
            self._generation += 1

            # Evaluate (Layer 12)
            Evaluator.evaluate(self._population, eval_fn, context)

            # Archive update (Layer 9)
            self._archive.update(self._population)

            # Track history
            best = max(c.fitness for c in self._population)
            self._fitness_history.append(best)
            self._diversity_history.append(DiversityEngine.compute(self._population))

            # Controller adaptation (Layer 10)
            params = self._controller.adapt(self._population)
            self._params_history.append(params)

            # Selection (Layer 6)
            parents = SelectionEngine.select(
                self._population,
                SelectionMethod.TOURNAMENT,
                self._tournament_size,
            )

            # Reproduction
            offspring = []
            for i in range(0, len(parents) - 1, 2):
                p1, p2 = parents[i], parents[i + 1]
                if random.random() < self._crossover_rate:
                    # Crossover (Layer 5)
                    operator = random.choice(list(CrossoverOperator))
                    c1, c2 = CrossoverEngine.crossover(p1, p2, operator)
                else:
                    c1, c2 = Chromosome(chromosome_id=str(uuid.uuid4())[:8],
                                        containers=list(p1.containers)), \
                             Chromosome(chromosome_id=str(uuid.uuid4())[:8],
                                        containers=list(p2.containers))

                # Mutation (Layer 4)
                strategy = random.choice(list(MutationStrategy))
                MutationEngine.mutate(c1, strategy, params["mutation_rate"], params["mutation_strength"])
                MutationEngine.mutate(c2, strategy, params["mutation_rate"], params["mutation_strength"])

                c1.age = 0
                c1.generation = self._generation
                c2.age = 0
                c2.generation = self._generation
                offspring.extend([c1, c2])

            # Elitism (Layer 7)
            self._population = ElitismEngine.combine(
                self._population, offspring, self._elite_count
            )
            self._population = self._population[:self._pop_size]

            # Age individuals
            for c in self._population:
                c.age += 1

        best_chromo = max(self._population, key=lambda c: c.fitness)

        # Restore original max_gen
        self._terminator._max_gen = original_max_gen

        return {
            "best_chromosome": best_chromo,
            "best_fitness": best_chromo.fitness,
            "generation": self._generation,
            "converged": self._terminator.is_converged,
            "convergence_reason": self._terminator.convergence_reason,
            "fitness_history": self._fitness_history,
            "diversity_history": self._diversity_history,
            "hall_of_fame": self._archive.hall_of_fame,
            "params_history": self._params_history,
            "best_genes": {
                g.name: g.value
                for g in CrossoverEngine._flatten(best_chromo)
            },
        }

    def _initialize_population(self, specs: Dict[str, Tuple[float, float]]) -> List[Chromosome]:
        """Initialize random population."""
        population = []
        for i in range(self._pop_size):
            container = GeneContainer(
                container_id=f"ctx_{i}",
                name="main",
                genes=[
                    Gene(
                        gene_id=f"g_{name}_{i}",
                        name=name,
                        value=random.uniform(lo, hi),
                        min_val=lo,
                        max_val=hi,
                    )
                    for name, (lo, hi) in specs.items()
                ],
            )
            chromo = Chromosome(
                chromosome_id=str(uuid.uuid4())[:8],
                containers=[container],
                age=0,
                generation=0,
            )
            population.append(chromo)
        return population

    @staticmethod
    def _default_gene_specs() -> Dict[str, Tuple[float, float]]:
        """Default gene specifications."""
        return {
            "exploration_rate": (0.01, 0.5),
            "learning_rate": (0.001, 0.1),
            "temperature": (0.1, 1.0),
            "memory_weight": (0.1, 0.9),
            "stability_factor": (0.5, 1.0),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            "generation": self._generation,
            "population_size": len(self._population),
            "current_best": self._fitness_history[-1] if self._fitness_history else 0.0,
            "current_diversity": self._diversity_history[-1] if self._diversity_history else 0.0,
            "hof_size": len(self._archive.hall_of_fame),
            "converged": self._terminator.is_converged,
            "convergence_reason": self._terminator.convergence_reason,
            "current_params": {
                "mutation_rate": self._controller.mutation_rate,
                "mutation_strength": self._controller.mutation_strength,
            },
        }
    
    def evaluate(self) -> Dict[str, Any]:
        """Evaluate current population (兼容别名)."""
        if not self._population:
            return {"fitness": 0.0, "diversity": 0.0}
        best = max(c.fitness for c in self._population)
        diversity = DiversityEngine.compute(self._population)
        return {
            "fitness": best,
            "diversity": diversity,
            "generation": self._generation,
        }
