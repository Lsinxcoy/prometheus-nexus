"""CoEvolution — Multi-population co-evolution with Red Queen dynamics.

Based on: Red Queen hypothesis in evolutionary biology.
Co-evolving populations drive each other's fitness landscape.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import random
import math


class CoEvolution:
    """Co-evolution with Red Queen dynamics.

    Uses interdependent fitness functions where each population's
    fitness depends on the other populations' strategies.

    Usage:
        coevo = CoEvolution()
        coevo.evolve(["predator", "prey"], generations=10)
        stats = coevo.get_stats()
    """

    def __init__(self, niche_radius: float = 0.3):
        self._niche_radius = niche_radius
        self._populations: dict[str, list[dict]] = {}
        self._generation = 0
        self._history: list[dict] = []
        self._interaction_matrix: dict[tuple[str, str], float] = {}

    def evolve(self, contexts: list[str] | None = None, generations: int = 1):
        for ctx in (contexts or ["default"]):
            if ctx not in self._populations:
                self._populations[ctx] = [
                    {"genes": [random.random() for _ in range(5)], "fitness": 0.5,
                     "effective_fitness": 0.5, "wins": 0, "losses": 0}
                    for _ in range(10)
                ]

        for _ in range(generations):
            self._generation += 1

            # Phase 1: Interdependent fitness evaluation
            self._evaluate_interdependent_fitness()

            # Phase 2: Pairwise competition within niches
            self._niche_competition()

            # Phase 3: Selection + reproduction with crossover
            self._select_and_reproduce()

        stats = {}
        for name, pop in self._populations.items():
            avg = sum(i["fitness"] for i in pop) / max(len(pop), 1)
            stats[name] = avg
        self._history.append(stats)

    def _evaluate_interdependent_fitness(self):
        """Evaluate fitness based on inter-population interactions.

        Each population's fitness is modified by the strategies of
        opposing populations (Red Queen dynamic).
        """
        pop_names = list(self._populations.keys())

        for name, pop in self._populations.items():
            opponents = [n for n in pop_names if n != name]
            if not opponents:
                for ind in pop:
                    ind["effective_fitness"] = ind["fitness"]
                continue

            # Compute opponent average strategy
            opponent_genes = []
            for opp_name in opponents:
                for ind in self._populations[opp_name]:
                    opponent_genes.append(ind["genes"])

            if opponent_genes:
                avg_opp_gene = [
                    sum(g[i] for g in opponent_genes) / len(opponent_genes)
                    for i in range(len(opponent_genes[0]))
                ]
            else:
                avg_opp_gene = [0.5] * 5

            # Interdependent fitness: your fitness depends on beating opponent strategies
            for ind in pop:
                # Compute how well this individual's genes counter the opponent
                counter_score = 0.0
                for i, gene in enumerate(ind["genes"]):
                    if i < len(avg_opp_gene):
                        # Gene that is opposite to opponent gets higher fitness
                        counter_score += 1.0 - abs(gene - (1.0 - avg_opp_gene[i]))

                counter_score /= max(len(ind["genes"]), 1)

                # Base fitness + counter bonus
                base = sum(ind["genes"]) / len(ind["genes"])
                interaction_key = (name, tuple(opponents))
                coupling_strength = self._interaction_matrix.get(interaction_key, 0.5)
                self._interaction_matrix[interaction_key] = min(1.0, coupling_strength + 0.01)

                ind["effective_fitness"] = base * 0.4 + counter_score * 0.6 * coupling_strength

    def _niche_competition(self):
        """Within-niche tournament competition."""
        for name, pop in self._populations.items():
            if len(pop) < 2:
                continue

            for i in range(0, len(pop) - 1, 2):
                ind1, ind2 = pop[i], pop[i + 1]
                f1 = ind1.get("effective_fitness", ind1["fitness"])
                f2 = ind2.get("effective_fitness", ind2["fitness"])

                if f1 > f2:
                    ind1["wins"] = ind1.get("wins", 0) + 1
                    ind2["losses"] = ind2.get("losses", 0) + 1
                else:
                    ind2["wins"] = ind2.get("wins", 0) + 1
                    ind1["losses"] = ind1.get("losses", 0) + 1

    def _select_and_reproduce(self):
        """Tournament selection + crossover + mutation."""
        for name, pop in self._populations.items():
            # Sort by effective fitness
            pop.sort(key=lambda x: x.get("effective_fitness", x["fitness"]), reverse=True)

            # Elitism: keep top 20%
            elites = pop[:max(2, len(pop) // 5)]

            # Generate offspring
            new_pop = [dict(e) for e in elites]

            while len(new_pop) < len(pop):
                # Tournament selection
                p1 = self._tournament_select(elites)
                p2 = self._tournament_select(elites)

                # Crossover
                child_genes = []
                for i in range(min(len(p1["genes"]), len(p2["genes"]))):
                    if random.random() < 0.5:
                        child_genes.append(p1["genes"][i])
                    else:
                        child_genes.append(p2["genes"][i])

                # Mutation
                child_genes = [
                    max(0, min(1, g + random.gauss(0, 0.1)))
                    for g in child_genes
                ]

                new_pop.append({
                    "genes": child_genes,
                    "fitness": 0.0,
                    "effective_fitness": 0.0,
                    "wins": 0,
                    "losses": 0,
                })

            self._populations[name] = new_pop[:len(pop)]

    def _tournament_select(self, candidates: list[dict], k: int = 3) -> dict:
        """Tournament selection from candidates."""
        if not candidates:
            return {"genes": [0.5] * 5, "fitness": 0.5}
        selected = random.sample(candidates, min(k, len(candidates)))
        return max(selected, key=lambda x: x.get("effective_fitness", x["fitness"]))

    def get_stats(self) -> dict:
        return {
            "populations": len(self._populations),
            "generation": self._generation,
            "interaction_strength": sum(self._interaction_matrix.values()) / max(len(self._interaction_matrix), 1),
        }
