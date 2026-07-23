"""Tests for EvolutionEngine — 进化引擎核心 GA 算法契约(架构优化 P1: 补零单测盲区).

evolution_engine.py (911 行) 此前零针对性单元测试。本测试覆盖核心 GA 算子:
突变(MutationEngine)/ 交叉(CrossoverEngine)/ 选择(SelectionEngine)/
多样性(DiversityEngine)/ 精英(ElitismEngine)。

均为纯函数式静态方法, 不依赖 omega/store, 独立运行。
"""

from __future__ import annotations

import random

import pytest

from prometheus_nexus.evolution.evolution_engine import (
    Gene,
    GeneContainer,
    Chromosome,
    MutationStrategy,
    CrossoverOperator,
    SelectionMethod,
    MutationEngine,
    CrossoverEngine,
    SelectionEngine,
    DiversityEngine,
    ElitismEngine,
)


def _mk_chromosome(cid: str, vals: list[float], fit: float = 0.0) -> Chromosome:
    genes = [
        Gene(gene_id=f"g{i}", name=f"g{i}", value=v, min_val=0.0, max_val=1.0)
        for i, v in enumerate(vals)
    ]
    return Chromosome(
        chromosome_id=cid,
        containers=[GeneContainer(container_id="c", genes=genes)],
        fitness=fit,
    )


# ===================================================================
# 突变: 边界保持
# ===================================================================


def test_mutate_gaussian_stays_in_bounds():
    random.seed(42)
    c = _mk_chromosome("c1", [0.5, 0.5, 0.5])
    out = MutationEngine.mutate(c, MutationStrategy.GAUSSIAN, rate=1.0, strength=0.5)
    for g in out.containers[0].genes:
        assert 0.0 <= g.value <= 1.0


def test_mutate_uniform_within_bounds():
    random.seed(7)
    c = _mk_chromosome("c1", [0.5, 0.5])
    out = MutationEngine.mutate(c, MutationStrategy.UNIFORM, rate=1.0)
    for g in out.containers[0].genes:
        assert 0.0 <= g.value <= 1.0


def test_mutate_int_gene_rounded():
    random.seed(3)
    g = Gene(gene_id="gi", name="gi", value=0.5, min_val=0, max_val=10, gene_type="int")
    c = Chromosome(chromosome_id="ci", containers=[GeneContainer(container_id="c", genes=[g])])
    out = MutationEngine.mutate(c, MutationStrategy.GAUSSIAN, rate=1.0, strength=0.5)
    assert out.containers[0].genes[0].value == int(out.containers[0].genes[0].value)


# ===================================================================
# 交叉: 产生两个子代, 值在父代范围内
# ===================================================================


def test_crossover_single_point_returns_two():
    random.seed(11)
    p1 = _mk_chromosome("p1", [0.0, 0.0, 0.0, 0.0])
    p2 = _mk_chromosome("p2", [1.0, 1.0, 1.0, 1.0])
    c1, c2 = CrossoverEngine.crossover(p1, p2, CrossoverOperator.SINGLE_POINT)
    assert isinstance(c1, Chromosome) and isinstance(c2, Chromosome)
    # 每个子代基因数 == 父代
    assert len(c1.containers[0].genes) == 4
    assert len(c2.containers[0].genes) == 4


def test_crossover_blend_within_bounds():
    random.seed(5)
    p1 = _mk_chromosome("p1", [0.2, 0.8])
    p2 = _mk_chromosome("p2", [0.4, 0.6])
    c1, c2 = CrossoverEngine.crossover(p1, p2, CrossoverOperator.BLEND, alpha=0.5)
    for child in (c1, c2):
        for g in child.containers[0].genes:
            assert 0.0 <= g.value <= 1.0


def test_crossover_uniform_values_from_parents():
    random.seed(99)
    p1 = _mk_chromosome("p1", [0.0, 1.0])
    p2 = _mk_chromosome("p2", [1.0, 0.0])
    c1, c2 = CrossoverEngine.crossover(p1, p2, CrossoverOperator.UNIFORM)
    # 均匀交叉: 每个子代基因必为某父代的对应值
    for child in (c1, c2):
        for g in child.containers[0].genes:
            assert g.value in (0.0, 1.0)


# ===================================================================
# 选择: 返回子集, 精英被保留
# ===================================================================


def test_selection_tournament_returns_population_sized():
    pop = [
        _mk_chromosome(f"c{i}", [0.5], fit=float(i))
        for i in range(10)
    ]
    selected = SelectionEngine.select(pop, SelectionMethod.TOURNAMENT, tournament_size=4)
    # 锦标赛返回与种群等长(每轮选一个赢家)
    assert len(selected) == len(pop)


def test_selection_tournament_picks_high_fitness():
    random.seed(1)
    pop = [_mk_chromosome(f"c{i}", [0.5], fit=float(i)) for i in range(8)]
    # 多次锦标赛, 最优个体(c7, fit=7)应高频出现
    winners = set()
    for _ in range(20):
        s = SelectionEngine.select(pop, SelectionMethod.TOURNAMENT, tournament_size=4)
        winners.add(max(s, key=lambda c: c.fitness).chromosome_id)
    # 最优个体应被选中过
    assert "c7" in winners


def test_selection_elitism_preserves_best():
    weak = _mk_chromosome("weak", [0.5], fit=0.1)
    best = _mk_chromosome("best", [0.5], fit=0.99)
    old_pop = [weak] * 9 + [best]
    new_pop = [weak] * 10
    combined = ElitismEngine.combine(old_pop, new_pop, elite_count=1)
    # 精英(best)应存在于合并种群
    best_ids = [c.chromosome_id for c in combined if c.fitness >= 0.99]
    assert "best" in best_ids


# ===================================================================
# 多样性: 相同种群多样性低, 不同种群多样性高
# ===================================================================


def test_diversity_identical_population_low():
    pop = [_mk_chromosome(f"c{i}", [0.5, 0.5]) for i in range(5)]
    d = DiversityEngine.compute(pop)
    assert d == 0.0  # 完全相同 → 零多样性


def test_diversity_distinct_population_high():
    pop = [
        _mk_chromosome(f"c{i}", [i / 10.0, (10 - i) / 10.0]) for i in range(10)
    ]
    d = DiversityEngine.compute(pop)
    assert d > 0.0
