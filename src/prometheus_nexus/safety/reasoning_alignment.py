"""ReasoningAlignmentChecker — CARA 推理对齐检测 (arXiv 2606.08457).

论文核心方法：
一致性幻觉——多 Agent 答案一致但推理路径完全不同。
CARA 指标需统计检验：检测推理路径的显著分歧。
使用 Cohen's kappa 或相似度矩阵衡量推理对齐。

Extended with:
- Cohen's kappa for inter-rater agreement
- Proper statistical similarity matrices (pairwise Jaccard + overlap coefficient)
- Grounded Debate Protocol (GDP) as the key intervention
"""

from __future__ import annotations
import logging
import math
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _overlap_coefficient(set_a: set, set_b: set) -> float:
    """Overlap coefficient (Szymkiewicz-Simpson): |intersection| / min(|A|,|B|)."""
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / min(len(set_a), len(set_b))


def _cohens_kappa(ratings_a: list, ratings_b: list, n_categories: int = None) -> float:
    """Compute Cohen's kappa for inter-rater agreement.

    Args:
        ratings_a: List of categorical ratings from rater A.
        ratings_b: List of categorical ratings from rater B (same length).
        n_categories: Number of categories (inferred if None).

    Returns:
        Cohen's kappa coefficient in [-1, 1].
    """
    if len(ratings_a) != len(ratings_b) or len(ratings_a) == 0:
        return 0.0

    n = len(ratings_a)

    # Determine categories
    all_cats = set(ratings_a) | set(ratings_b)
    if n_categories is None:
        n_categories = max(len(all_cats), 2)

    # Observed agreement
    observed = sum(1 for a, b in zip(ratings_a, ratings_b) if a == b) / n

    # Expected agreement (by chance)
    count_a = Counter(ratings_a)
    count_b = Counter(ratings_b)
    expected = sum(
        (count_a.get(cat, 0) / n) * (count_b.get(cat, 0) / n)
        for cat in all_cats
    )

    denom = 1.0 - expected
    if abs(denom) < 1e-10:
        return 1.0  # perfect agreement or degenerate

    return round((observed - expected) / denom, 4)


def _extract_reasoning_steps(reasoning: str, max_steps: int = 15) -> list[str]:
    """Split reasoning string into a list of atomic step statements."""
    # Normalise sentence boundaries
    for sep in [". ", ".\n", "\n\n", "  "]:
        reasoning = reasoning.replace(sep, "\n")
    steps = [s.strip() for s in reasoning.split("\n") if s.strip()]
    # Filter out very short fragments
    steps = [s for s in steps if len(s) > 5]
    return steps[:max_steps]


def _word_set_from_steps(steps: list[str]) -> set[str]:
    """Extract a set of normalised content words from reasoning steps."""
    words = set()
    for step in steps:
        for token in step.lower().split():
            token = token.strip(".,!?;:()[]{}'\"")
            if len(token) > 2:
                words.add(token)
    return words


# ── ReasoningAlignmentChecker (extended) ──────────────────────────────────────


class ReasoningAlignmentChecker:
    """CARA — Consistency-Aware Reasoning Alignment with GDP intervention."""

    def __init__(self, kappa_threshold: float = 0.5,
                 similarity_threshold: float = 0.6):
        self._checks: list[dict] = []
        self._total = 0
        self._misalignments = 0
        self._kappa_threshold = kappa_threshold
        self._similarity_threshold = similarity_threshold
        self._gdp_sessions: list[dict] = []

    # ── original public API (unchanged signature) ─────────────────────────────

    def check_alignment(self, paths: list[dict]) -> dict:
        """检查多推理路径的对齐程度。

        Args:
            paths: [{"answer": str, "reasoning": str, "agent": str}, ...]

        Returns:
            {"cara_score": float, "aligned": bool, "disagreements": list[dict],
             "answer_consensus": float, "reasoning_divergence": float,
             "n_paths": int}
        """
        self._total += 1
        if len(paths) < 2:
            return {"cara_score": 1.0, "aligned": True, "disagreements": [],
                    "answer_consensus": 1.0, "reasoning_divergence": 0.0, "n_paths": len(paths)}

        answers = [p.get("answer", "") for p in paths]
        reasonings = [p.get("reasoning", "") for p in paths]

        # Step 1: Answer consensus — Cohen's kappa-like measure
        unique_answers = len(set(a.lower().strip() for a in answers if a))
        answer_consensus = 1.0 if unique_answers <= 1 else 1.0 / unique_answers

        # Step 2: Reasoning divergence — pairwise n-gram overlap
        if any(r for r in reasonings):
            reasoning_steps = []
            for r in reasonings:
                steps = [s.strip() for s in r.replace(".", "\n").split("\n") if s.strip()]
                reasoning_steps.append(steps[:10])  # 取前 10 个步骤

            pairwise_similarities = []
            for i in range(len(reasoning_steps)):
                for j in range(i + 1, len(reasoning_steps)):
                    steps_i = set(reasoning_steps[i])
                    steps_j = set(reasoning_steps[j])
                    if not steps_i or not steps_j:
                        continue
                    jaccard = len(steps_i & steps_j) / len(steps_i | steps_j)
                    pairwise_similarities.append(jaccard)

            reasoning_divergence = 1.0 - (sum(pairwise_similarities) / max(len(pairwise_similarities), 1)) if pairwise_similarities else 1.0
        else:
            reasoning_divergence = 0.0

        # Step 3: CARA = answer consensus × (1 - reasoning divergence)
        cara_score = answer_consensus * (1.0 - reasoning_divergence)

        # Step 4: 判断是否对齐
        aligned = cara_score >= 0.5
        if not aligned:
            self._misalignments += 1

        # Step 5: 找出分歧点
        disagreements = []
        if not aligned:
            for i in range(len(paths)):
                for j in range(i + 1, len(paths)):
                    if reasoning_steps[i] and reasoning_steps[j]:
                        diff_steps = list(set(reasoning_steps[i]) - set(reasoning_steps[j]))
                        if diff_steps:
                            disagreements.append({
                                "agent_a": paths[i].get("agent", i),
                                "agent_b": paths[j].get("agent", j),
                                "shared_steps": len(set(reasoning_steps[i]) & set(reasoning_steps[j])),
                                "diff_steps": diff_steps[:3],
                            })

        result = {
            "cara_score": round(cara_score, 4),
            "aligned": aligned,
            "answer_consensus": round(answer_consensus, 4),
            "reasoning_divergence": round(reasoning_divergence, 4),
            "disagreements": disagreements[:5],
            "n_paths": len(paths),
        }
        self._checks.append(result)
        return result

    # ── Cohen's kappa alignment ───────────────────────────────────────────────

    def compute_kappa_alignment(self, paths: list[dict]) -> dict:
        """Compute full statistical similarity matrix with Cohen's kappa.

        Treats each reasoning path as a "rater" producing step categories.
        Returns pairwise kappa values and an aggregate inter-rater agreement score.

        Args:
            paths: [{"answer": str, "reasoning": str, "agent": str}, ...]

        Returns:
            {"pairwise_kappa": list[dict], "mean_kappa": float,
             "pairwise_jaccard_similarity": list[dict],
             "pairwise_overlap": list[dict], "n_paths": int}
        """
        n = len(paths)
        if n < 2:
            return {"pairwise_kappa": [], "mean_kappa": 1.0,
                    "pairwise_jaccard_similarity": [], "pairwise_overlap": [],
                    "n_paths": n}

        # Extract reasoning step labels for each path
        path_steps: list[list[str]] = []
        path_word_sets: list[set[str]] = []
        for p in paths:
            steps = _extract_reasoning_steps(p.get("reasoning", ""))
            path_steps.append(steps)
            path_word_sets.append(_word_set_from_steps(steps))

        pairwise_kappa = []
        pairwise_jaccard = []
        pairwise_overlap = []

        for i in range(n):
            for j in range(i + 1, n):
                agent_i = paths[i].get("agent", f"agent_{i}")
                agent_j = paths[j].get("agent", f"agent_{j}")

                # Cohen's kappa on steps (treating each step as a category label)
                kappa = _cohens_kappa(path_steps[i], path_steps[j])

                # Jaccard on word sets
                jaccard = _jaccard_similarity(path_word_sets[i], path_word_sets[j])

                # Overlap coefficient
                overlap = _overlap_coefficient(path_word_sets[i], path_word_sets[j])

                pairwise_kappa.append({
                    "agents": (agent_i, agent_j),
                    "kappa": kappa,
                    "interpretation": self._kappa_interpretation(kappa),
                })
                pairwise_jaccard.append({
                    "agents": (agent_i, agent_j),
                    "jaccard": round(jaccard, 4),
                })
                pairwise_overlap.append({
                    "agents": (agent_i, agent_j),
                    "overlap": round(overlap, 4),
                })

        mean_kappa = round(
            sum(pk["kappa"] for pk in pairwise_kappa) / max(len(pairwise_kappa), 1), 4
        )

        return {
            "pairwise_kappa": pairwise_kappa,
            "mean_kappa": mean_kappa,
            "pairwise_jaccard_similarity": pairwise_jaccard,
            "pairwise_overlap": pairwise_overlap,
            "n_paths": n,
        }

    # ── similarity matrix ─────────────────────────────────────────────────────

    def build_similarity_matrix(self, paths: list[dict]) -> dict:
        """Build a proper statistical similarity matrix (word-set Jaccard).

        Returns a square matrix (n x n) of pairwise Jaccard similarities.

        Args:
            paths: [{"reasoning": str, ...}, ...]

        Returns:
            {"matrix": list[list[float]], "labels": list[str], "n": int}
        """
        n = len(paths)
        labels = [p.get("agent", f"agent_{i}") for i, p in enumerate(paths)]
        word_sets = [_word_set_from_steps(_extract_reasoning_steps(p.get("reasoning", "")))
                     for p in paths]

        matrix = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i, n):
                sim = _jaccard_similarity(word_sets[i], word_sets[j])
                matrix[i][j] = round(sim, 4)
                matrix[j][i] = round(sim, 4)

        return {"matrix": matrix, "labels": labels, "n": n}

    # ── Grounded Debate Protocol (GDP) ────────────────────────────────────────

    def grounded_debate(self, paths: list[dict],
                        debate_rounds: int = 3,
                        callback: callable = None) -> dict:
        """Grounded Debate Protocol (GDP) intervention.

        Simulates a structured debate between agents to reduce consistency
        illusion. After debate, CARA metrics are recomputed.

        The protocol:
        - Round 1: Each agent sees all others' reasoning and provides critique.
        - Round 2: Agents can revise their reasoning based on critiques.
        - Round 3: Final alignment check.

        Args:
            paths: Initial reasoning paths (as in check_alignment).
            debate_rounds: Number of debate rounds (default 3).
            callback: Optional callable(paths, round) -> revised_paths
                      for external integration. If None, uses built-in
                      heuristic revision.

        Returns:
            {"gdp_result": list[dict], "pre_debate_cara": dict,
             "post_debate_cara": dict, "delta": dict,
             "kappa_pre": float, "kappa_post": float}
        """
        pre_cara = self.check_alignment(paths)
        pre_kappa = self.compute_kappa_alignment(paths)

        # Deep copy paths for modification
        current_paths = [dict(p) for p in paths]
        debate_log = []

        for rnd in range(1, debate_rounds + 1):
            if callback:
                current_paths = callback(current_paths, rnd)
            else:
                current_paths = self._default_debate_step(current_paths, rnd)

            round_analysis = self.compute_kappa_alignment(current_paths)
            round_cara = self.check_alignment(current_paths)

            debate_log.append({
                "round": rnd,
                "mean_kappa": round_analysis["mean_kappa"],
                "cara_score": round_cara["cara_score"],
                "aligned": round_cara["aligned"],
                "n_paths": len(current_paths),
            })

        post_cara = self.check_alignment(current_paths)
        post_kappa = self.compute_kappa_alignment(current_paths)

        result = {
            "gdp_result": debate_log,
            "pre_debate_cara": pre_cara,
            "post_debate_cara": post_cara,
            "delta": {
                "cara_score_change": round(
                    post_cara["cara_score"] - pre_cara["cara_score"], 4
                ),
                "kappa_change": round(
                    post_kappa["mean_kappa"] - pre_kappa["mean_kappa"], 4
                ),
                "reasoning_divergence_change": round(
                    post_cara["reasoning_divergence"] - pre_cara["reasoning_divergence"], 4
                ),
            },
            "kappa_pre": pre_kappa["mean_kappa"],
            "kappa_post": post_kappa["mean_kappa"],
        }
        self._gdp_sessions.append(result)
        return result

    def _default_debate_step(self, paths: list[dict], round_num: int) -> list[dict]:
        """Built-in heuristic debate step.

        Round 1: Agents annotate which reasoning steps they disagree with.
        Round 2: Agents optionally drop contested steps, keeping only shared steps.
        Round 3+: Light refinement — rephrase remaining steps for clarity.
        """
        revised = []
        n = len(paths)

        for idx, p in enumerate(paths):
            steps = _extract_reasoning_steps(p.get("reasoning", ""))
            word_set = _word_set_from_steps(steps)
            new_p = dict(p)

            if round_num == 1:
                # Annotation: mark which steps are unique vs shared
                shared_words = set(word_set)
                for j, other in enumerate(paths):
                    if j == idx:
                        continue
                    other_words = _word_set_from_steps(
                        _extract_reasoning_steps(other.get("reasoning", ""))
                    )
                    shared_words &= other_words

                unique_words = word_set - shared_words
                new_p["gdp_notes"] = {
                    "shared_word_count": len(shared_words),
                    "unique_word_count": len(unique_words),
                    "unique_terms": list(unique_words)[:5],
                }

            elif round_num == 2:
                # Revision: drop contested steps, keep only those with
                # majority overlap
                all_shared = set(word_set)
                for j, other in enumerate(paths):
                    if j == idx:
                        continue
                    other_words = _word_set_from_steps(
                        _extract_reasoning_steps(other.get("reasoning", ""))
                    )
                    all_shared &= other_words

                filtered_steps = [s for s in steps
                                  if len(set(s.lower().split()) & all_shared) > 0]
                if filtered_steps:
                    new_p["reasoning"] = ". ".join(filtered_steps)
                new_p["revised_in_round"] = round_num
            else:
                # Round 3+: minor rephrasing (no-op in default heuristic)
                new_p["debate_round"] = round_num

            revised.append(new_p)

        return revised

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _kappa_interpretation(kappa: float) -> str:
        """Interpret Cohen's kappa value."""
        if kappa < 0.0:
            return "worse than chance"
        elif kappa < 0.2:
            return "slight agreement"
        elif kappa < 0.4:
            return "fair agreement"
        elif kappa < 0.6:
            return "moderate agreement"
        elif kappa < 0.8:
            return "substantial agreement"
        else:
            return "almost perfect agreement"

    # ── stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "total_checks": self._total,
            "misalignments": self._misalignments,
            "misalignment_rate": round(
                self._misalignments / max(self._total, 1), 4
            ),
            "gdp_sessions": len(self._gdp_sessions),
        }


# ─────────────────────────────────────────────────────────────────────────────
# 架构优化 P1: 声明式接入适配器 (2026-07-23)
# 原 ReasoningAlignmentChecker 实现完整但零调用(死代码)。本适配器继承
# BaseMechanism, 委托原 check_alignment, 声明 auto_wire=True + phase=REASON,
# 使上帝(Omega)可经 registry/wiring 按阶段声明式调度, 无需改 life.py 5333 行。
# 原类实现零改动 — 保留已验证逻辑。
# ─────────────────────────────────────────────────────────────────────────────
from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism, Phase


class CARAMechanism(BaseMechanism):
    """CARA 推理对齐检测的声明式接入适配器."""

    name = "cara_alignment"
    description = "Consistency-Aware Reasoning Alignment (arXiv 2606.08457) — 检测多路径推理一致性幻觉"
    category = "safety"
    phase = Phase.REASON          # 推理后阶段调度
    hooks_into = "post_reason"
    auto_wire = True

    def __init__(self, kappa_threshold: float = 0.5, similarity_threshold: float = 0.6):
        super().__init__()
        self._inner = ReasoningAlignmentChecker(
            kappa_threshold=kappa_threshold, similarity_threshold=similarity_threshold
        )

    def run(self, context: dict | None = None) -> dict:
        """context: {"paths": [{"answer","reasoning","agent"}, ...]}.

        Returns: 原 check_alignment 结果 + ok 字段(符合 BaseMechanism 契约).
        """
        paths = (context or {}).get("paths", [])
        result = self._inner.check_alignment(paths)
        result["ok"] = True
        return result
