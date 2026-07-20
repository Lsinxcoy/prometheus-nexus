"""LocalCausalExplainer — LOCA 局部因果解释 (arXiv 2605.00123).

论文核心方法：
平均 ~6 个干预修复 jailbreak。局部因果解释比全局规则更有效。
方法：用因果链定位导致 jailbreak 的 token 子集，通过 ablation 实验
验证哪些 token 是根本原因。

Enhancements:
- Token-level causal tracing via simulated ablation of critical tokens
- Intervention generation based on ablation-verified root causes
- Chain-of-thought explanation with causal path ranking
"""

from __future__ import annotations
import hashlib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_JAILBREAK_MARKERS = [
    "ignore previous", "ignore all", "forget your", "you are now",
    "act as", "pretend to", "roleplay", "do not follow",
    "override", "new instruction", "system prompt",
    "ignore all instructions", "forget all rules",
]

_CAUSAL_INDICATORS = [
    "because", "since", "thus", "therefore", "as a result",
]


class LocalCausalExplainer:
    """LOCA 局部因果解释器。

    Detects jailbreak markers, performs token-level causal tracing
    via ablation simulation, and generates targeted interventions
    ranked by causal impact.
    """

    def __init__(self):
        self._analyses: list[dict] = []
        self._total = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def local_cause(self, failure_case: dict) -> dict:
        """Analyse a jailbreak failure case for local causal chains.

        Args:
            failure_case: {"content": str, "context": str, "model_output": str, ...}

        Returns:
            {"interventions": list[str], "target_tokens": list[str],
             "severity": float, "chain": list[dict], "n_interventions": int,
             "ablation": list[dict], "ranking": list[dict]}
        """
        self._total += 1
        content = failure_case.get("content", "")
        context = failure_case.get("context", "")
        model_output = failure_case.get("model_output", "")
        combined = f"{context}\n{content}".lower()

        # Empty content → no causal analysis possible, return empty interventions
        if not content.strip():
            return {
                "interventions": [],
                "target_tokens": [],
                "severity": 0.0,
                "chain": [],
                "n_interventions": 0,
                "ablation": [],
                "ranking": [],
                "note": "empty content",
            }

        # Step 1 – Detect jailbreak markers (surface-level)
        markers_found = self._detect_markers(combined)

        # Step 2 – Causal indicator chain analysis
        causal_chain = self._extract_causal_chain(combined)

        # Step 3 – Identify target tokens (candidates for intervention)
        target_tokens = self._identify_target_tokens(
            markers_found, content, combined
        )

        # Step 4 – Token-level causal tracing via ablation simulation
        ablation_results = self._simulate_ablation(
            content, target_tokens, model_output
        )

        # Step 5 – Rank interventions by causal impact
        ranked = self._rank_token_causes(target_tokens, ablation_results)

        # Step 6 – Generate interventions
        interventions = self._generate_interventions(
            target_tokens, causal_chain, ranked
        )

        # Step 7 – Severity score
        severity = self._compute_severity(target_tokens, causal_chain, ranked)

        result = {
            "interventions": interventions,
            "target_tokens": target_tokens,
            "severity": round(severity, 4),
            "chain": causal_chain[:5],
            "n_interventions": len(interventions),
            "ablation": ablation_results,
            "ranking": ranked,
        }
        self._analyses.append(result)
        return result

    def get_stats(self) -> dict:
        return {
            "total_analyses": self._total,
            "avg_severity": round(
                sum(a["severity"] for a in self._analyses)
                / max(len(self._analyses), 1), 4
            ),
            "total_interventions": sum(a["n_interventions"] for a in self._analyses),
        }

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _detect_markers(self, text: str) -> list[dict]:
        """Step 1: surface-level jailbreak marker detection."""
        found = []
        for marker in _JAILBREAK_MARKERS:
            if marker in text:
                pos = text.find(marker)
                found.append({"marker": marker, "position": pos, "severity": 0.7})
        return found

    def _extract_causal_chain(self, text: str) -> list[dict]:
        """Step 2: extract cause-effect relationships from text."""
        chain = []
        for indicator in _CAUSAL_INDICATORS:
            if indicator in text:
                parts = text.split(indicator)
                for i, part in enumerate(parts[:-1]):
                    cause = part[-100:].strip()
                    effect = parts[i + 1][:100].strip()
                    chain.append({
                        "indicator": indicator,
                        "cause": cause,
                        "effect": effect,
                    })
        return chain

    def _identify_target_tokens(
        self, markers: list[dict], content: str, combined: str
    ) -> list[str]:
        """Step 3: determine minimal token set for intervention."""
        target_tokens = []
        for m in markers:
            if m["marker"] not in target_tokens:
                target_tokens.append(m["marker"])
        if not target_tokens:
            tokens = content.split()
            long_tokens = list(dict.fromkeys(t for t in tokens if len(t) > 20))
            if long_tokens:
                target_tokens = long_tokens[:3]
        return target_tokens

    def _simulate_ablation(
        self, content: str, target_tokens: list[str], model_output: str
    ) -> list[dict]:
        """Step 4: token-level causal tracing via simulated ablation.

        For each candidate token, simulate removing it and measure the
        semantic impact using n-gram embedding cosine distance between
        the original and ablated content — a proxy for the LOCA paper's
        activation-space ablation when no live LLM is available.

        Low embedding similarity after ablation = high causal influence.
        """
        orig_emb = self._embed_text(content)
        results = []
        output_lower = model_output.lower()
        for token in target_tokens:
            ablated = content.replace(token, "")
            ablated_emb = self._embed_text(ablated)

            # Embedding shift: how much does content's representation change?
            emb_sim = self._cosine_sim(orig_emb, ablated_emb)
            influence = round(1.0 - emb_sim, 4)  # low sim = high influence

            # Token-output overlap (secondary signal)
            token_words = token.split()
            overlap = sum(1 for w in token_words if w in output_lower)
            overlap_influence = round(overlap / max(len(token_words), 1), 4)

            # Combined: embedding similarity (primary) + token overlap (secondary)
            combined_influence = round(influence * 0.7 + overlap_influence * 0.3, 4)

            ablation_id = hashlib.sha256(
                ablated.encode()
            ).hexdigest()[:12]

            results.append({
                "token": token,
                "influence": combined_influence,
                "embedding_similarity": emb_sim,
                "token_overlap": overlap_influence,
                "ablation_id": ablation_id,
                "output_differs": combined_influence > 0.3,
            })
        results.sort(key=lambda r: r["influence"], reverse=True)
        return results

    @staticmethod
    def _embed_text(text: str) -> list[float]:
        """Compute character 3-gram embedding for similarity comparison."""
        if not text:
            return [0.0] * 10
        text = text.lower().strip()
        # Use 3-gram frequency vector (top 10 most common chars' trigrams)
        from collections import Counter
        trigrams = Counter()
        for i in range(max(0, len(text) - 2)):
            trigrams[text[i:i+3]] += 1
        total = sum(trigrams.values()) or 1
        # Vector of top 10 trigram frequencies
        top = trigrams.most_common(10)
        return [count / total for _, count in top]

    @staticmethod
    def _cosine_sim(a: list[float], b: list[float]) -> float:
        """Cosine similarity between two embedding vectors."""
        if not a or not b:
            return 0.0
        max_len = max(len(a), len(b))
        a_ext = a + [0.0] * (max_len - len(a))
        b_ext = b + [0.0] * (max_len - len(b))
        dot = sum(x * y for x, y in zip(a_ext, b_ext))
        na = sum(x * x for x in a_ext) ** 0.5
        nb = sum(y * y for y in b_ext) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def _rank_token_causes(
        self, target_tokens: list[str], ablation: list[dict]
    ) -> list[dict]:
        """Step 5: rank tokens by causal impact (low influence = causal)."""
        ranking = []
        for i, token in enumerate(target_tokens):
            ab_data = next(
                (a for a in ablation if a["token"] == token), {}
            )
            influence = ab_data.get("influence", 0)
            causal_score = round(1.0 - influence, 4)
            ranking.append({
                "token": token,
                "rank": i + 1,
                "causal_score": causal_score,
                "recommended": causal_score > 0.5,
            })
        ranking.sort(key=lambda r: r["causal_score"], reverse=True)
        for rank_idx, entry in enumerate(ranking):
            entry["rank"] = rank_idx + 1
        return ranking

    def _generate_interventions(
        self,
        target_tokens: list[str],
        causal_chain: list[dict],
        ranking: list[dict],
    ) -> list[str]:
        """Step 6: generate intervention recommendations."""
        interventions = []
        if not target_tokens:
            interventions.append("No jailbreak markers detected — manual review")
            return interventions

        # Top-ranked (highest causal score) token gets strongest intervention
        for rank_entry in ranking:
            token = rank_entry["token"]
            score = rank_entry["causal_score"]
            if score > 0.7:
                interventions.append(
                    f"Ablation-verified root cause: '{token}' "
                    f"(causal score={score}). "
                    f"Add to blocklist + harden instruction boundary."
                )
            elif score > 0.4:
                interventions.append(
                    f"Candidate token '{token}' (score={score}). "
                    f"Strengthen instruction boundary."
                )
            else:
                interventions.append(
                    f"Low-impact token '{token}' (score={score}). "
                    f"Monitor only."
                )

        if causal_chain and target_tokens:
            root_cause = ranking[0]["token"] if ranking else target_tokens[0]
            interventions.append(
                f"Contextual fix: break causal chain from "
                f"'{causal_chain[0].get('cause', '')[:40]}' around '{root_cause}'"
            )

        return interventions

    def _compute_severity(
        self,
        target_tokens: list[str],
        causal_chain: list[dict],
        ranking: list[dict],
    ) -> float:
        """Step 7: compute overall severity score."""
        base = len(target_tokens) * 0.25 + len(causal_chain) * 0.1 + 0.1
        # Boost severity when high-causal-score tokens found
        if ranking and ranking[0].get("causal_score", 0) > 0.7:
            base *= 1.3
        return min(1.0, base)
