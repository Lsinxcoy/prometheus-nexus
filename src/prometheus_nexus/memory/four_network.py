"""FourNetworkMemory — 4-network cognitive memory with retrieval scoring.

参考: "Generative Agents: Interactive Simulacra of Human Behavior"
(arXiv:2304.03442, Park et al. 2023) 中的 retrieval scoring 公式:
    score = recency^δ × importance × relevance

当前实现:
- 4-network split（experience/semantic/procedural/episodic）— 这是对原论文
  单 memory stream 的扩展，非原文设计
- Retrieval scoring: recency_decay × importance × keyword_relevance
- Reflection: 基于关键词的模式提取和跨网络洞察合成（非原文的 LLM 驱动，
  但使用更复杂的主题/矛盾/模式检测替代简单拼接）
- Planning: 基于反射生成行动计划

差异说明:
- 原文使用单条 memory stream；4-network split 是本实现的创新扩展
- 原文的 reflection 用 LLM 合成高层洞察；本实现使用规则+模式匹配合成
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import math
import time
from collections import defaultdict, Counter
from typing import Any


class FourNetworkMemory:
    """4-network cognitive memory with Generative Agents principles.

    Networks: experience, semantic, procedural, episodic
    Retrieval: recency × importance × relevance (from Generative Agents paper)
    """

    NETWORK_NAMES = ("experience", "semantic", "procedural", "episodic")
    NETWORK_KEYWORDS = {
        "experience": {"happened", "occurred", "event", "time", "when", "before", "after",
                       "encountered", "experienced", "witnessed", "observed", "noticed"},
        "semantic": {"is", "means", "definition", "concept", "category", "type",
                     "represents", "defined", "refers", "constitutes", "classified",
                     "the concept of", "is defined as", "refers to", "involves",
                     "characterized by", "essentially", "fundamentally"},
        "procedural": {"how", "step", "process", "method", "technique", "algorithm",
                       "procedure", "protocol", "approach", "strategy", "workflow",
                       "first", "second", "third", "then", "after that", "next",
                       "following", "subsequently", "finally", "initially"},
        "episodic": {"where", "location", "context", "situation", "episode", "story",
                     "scene", "setting", "circumstance", "scenario", "incident",
                     "in", "at", "on", "from", "to", "into", "during", "while",
                     "as soon as", "upon", "throughout"},
    }
    # 【P1修复】多信号评分权重
    NETWORK_SIGNAL_WEIGHTS = {
        "keyword": 0.4,      # 关键词匹配
        "structure": 0.3,    # 结构特征（步骤、列表等）
        "temporal": 0.2,     # 时间线索
        "content_type": 0.1, # 内容类型暗示
    }

    def __init__(self, max_entries_per_network: int = 1000, recency_decay: float = 0.95):
        """Initialize with Generative Agents parameters.

        Args:
            max_entries_per_network: Maximum entries per network.
            recency_decay: Decay factor for recency scoring (from GA paper).
        """
        self._networks: dict[str, list[dict]] = {name: [] for name in self.NETWORK_NAMES}
        self._tag_index: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self._max_entries = max_entries_per_network
        self._recency_decay = recency_decay
        self._total_retained = 0
        self._access_counter = 0
        # Reflection state
        self._reflections: list[dict] = []
        self._plans: list[dict] = []
        self._last_reflection_time = 0.0

    def retain(self, content: str, network: str | None = None,
               tags: list[str] | None = None, importance: float = 0.5) -> bool:
        """Retain a memory in a specific network or auto-classify.

        If network is None, auto-classifies based on content keywords.
        """
        # Auto-classify if no network specified
        if network is None:
            network = self._auto_classify(content)
            logger.debug("Auto-classified to network: %s", network)

        if network not in self._networks:
            return False

        entry = {
            "content": content, "importance": importance,
            "tags": tags or [], "network": network,
            "access_count": 0, "last_access": time.time(),
        }

        net = self._networks[network]
        if len(net) >= self._max_entries:
            net.pop(0)
        idx = len(net)
        net.append(entry)

        for tag in (tags or []):
            self._tag_index[tag].append((network, idx))

        self._total_retained += 1
        return True

    def _auto_classify(self, content: str) -> str:
        """Auto-classify content into the most appropriate network.
        
        Enhanced with multi-signal scoring:
        1. Keyword matching (weight: 0.4)
        2. Structural signals (weight: 0.3) - steps, lists, procedures
        3. Temporal signals (weight: 0.2) - time references
        4. Content type hints (weight: 0.1)
        
        Classification rules based on Generative Agents paper:
        - experience: events that happened, temporal references
        - semantic: concepts, definitions, categories
        - procedural: steps, methods, processes
        - episodic: locations, contexts, situations
        """
        content_lower = content.lower()
        words = set(content_lower.split())
        
        # Remove stopwords that appear in all networks
        common_stopwords = {"the", "a", "an", "is", "was", "were", "are", "be", "been",
                           "being", "have", "has", "had", "do", "does", "did", "will",
                           "would", "could", "should", "may", "might", "can", "shall",
                           "to", "of", "in", "for", "on", "with", "at", "by", "from",
                           "as", "into", "through", "during", "before", "after", "above",
                           "below", "between", "about", "up", "out", "off", "over",
                           "and", "but", "or", "nor", "not", "so", "yet", "both",
                           "either", "neither", "this", "that", "these", "those",
                           "very", "just", "too", "also", "only", "more", "most",
                           "some", "any", "each", "every", "all", "both", "few",
                           "own", "same", "other", "another", "such", "which", "what",
                           "who", "whom", "whose", "it", "its", "i", "we", "you",
                           "he", "she", "they", "me", "him", "her", "us", "them"}
        
        filtered_words = words - common_stopwords
        
        # Multi-signal scoring
        scores = {net: 0.0 for net in self.NETWORK_NAMES}
        
        # Signal 1: Keyword matching (weight: 0.4)
        for net_name, keywords in self.NETWORK_KEYWORDS.items():
            relevant_keywords = keywords - common_stopwords
            overlap = filtered_words & relevant_keywords
            weighted_score = 0
            for word in overlap:
                length_weight = min(len(word) / 5, 1.0)
                weighted_score += length_weight
            scores[net_name] += weighted_score * self.NETWORK_SIGNAL_WEIGHTS["keyword"]
        
        # Signal 2: Structural signals (weight: 0.3)
        # Procedural indicators: numbered steps, ordered sequences
        if any(kw in content_lower for kw in ["step 1", "step 2", "first:", "second:", "third:"]):
            scores["procedural"] += 0.3
        # Semantic indicators: definition patterns
        if any(kw in content_lower for kw in ["is defined as", "means", "refers to", "concept of"]):
            scores["semantic"] += 0.3
        # Episodic indicators: location markers
        if any(kw in content_lower for kw in ["at location", "in the scene", "during the episode"]):
            scores["episodic"] += 0.3
        
        # Signal 3: Temporal signals (weight: 0.2)
        temporal_markers = ["when", "after", "before", "during", "while", "then", "next", "finally"]
        if any(tm in content_lower for tm in temporal_markers):
            # Could be experience or episodic
            scores["experience"] += 0.1
            scores["episodic"] += 0.1
        
        # Signal 4: Content type hints (weight: 0.1)
        # Longer, structured content tends to be procedural/semantic
        if len(content) > 200 and any(w in content_lower for w in ["how to", "method", "algorithm"]):
            scores["procedural"] += 0.1
        if len(content) < 100 and any(w in content_lower for w in ["happened", "occurred"]):
            scores["experience"] += 0.1

        # Signal 5: Copular ("X is a Y" / "X is Y") → semantic concept/definition
        # Generative Agents: declarative statements of fact are semantic memory.
        import re as _re
        if _re.search(r"\b(is|are|was|were)\s+(a|an|the)?\s*\w+", content_lower):
            scores["semantic"] += 0.35
        # Explicit concept keywords
        if any(kw in content_lower for kw in ["programming", "language", "concept", "definition", "theory", "algorithm", "model", "framework"]):
            scores["semantic"] += 0.15

        # Return network with highest score, default to experience
        if scores:
            best_network = max(scores, key=scores.get)
            # 【P1修复】降低阈值到0.3，允许更少信号也能分类
            if scores[best_network] >= 0.3:
                return best_network
        
        return "experience"  # Default fallback

    def recall(self, query: str, top_k: int = 5, network: str | None = None) -> list[dict]:
        """Recall with Generative Agents scoring: recency × importance × relevance.

        Uses tag index for O(K) candidate selection instead of O(N) full scan.
        """
        results = []
        query_lower = query.lower()
        query_words = set(query_lower.split())
        networks = [network] if network and network in self._networks else self.NETWORK_NAMES

        # Phase 1: Collect candidates via tag index (O(K) instead of O(N))
        candidate_entries = set()
        for tag in query_words:
            if tag in self._tag_index:
                for net_name, idx in self._tag_index[tag]:
                    if net_name in self._networks and idx < len(self._networks[net_name]):
                        candidate_entries.add((net_name, idx))

        # Also add recent entries (last 5 per network) for recency bonus
        for net_name in networks:
            net = self._networks[net_name]
            for i in range(max(0, len(net) - 5), len(net)):
                candidate_entries.add((net_name, i))

        # Phase 2: Score only candidates
        for net_name, idx in candidate_entries:
            entry = self._networks[net_name][idx]

            content_lower = entry["content"].lower()
            relevance = 0.0
            if query_lower in content_lower:
                relevance = 1.0
            content_words = set(content_lower.split())
            overlap = query_words & content_words
            if query_words:
                relevance += len(overlap) / len(query_words) * 0.5

            net_keywords = self.NETWORK_KEYWORDS.get(net_name, set())
            keyword_overlap = query_words & net_keywords
            if keyword_overlap:
                relevance *= 1.0 + len(keyword_overlap) * 0.1

            if relevance == 0:
                continue

            importance = entry.get("importance", 0.5)
            age = time.time() - entry.get("last_access", time.time())
            recency = math.exp(-age / 3600)

            # Generative Agents multiplicative formula: score = recency^δ × importance × relevance
            # Using δ=1.0 (default) for standard exponential recency decay
            # Add small epsilon to avoid zero-score for highly relevant content
            recency_decay = recency ** 0.5  # δ = 0.5 for square-root decay
            score = recency_decay * importance * relevance + 1e-10

            entry["access_count"] = entry.get("access_count", 0) + 1
            entry["last_access"] = time.time()

            results.append({
                "content": entry["content"],
                "score": score,
                "network": net_name,
                "importance": importance,
                "recency": recency,
                "relevance": relevance,
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    # ------------------------------------------------------------------
    # LLM Reflection (Generative Agents — arXiv 2304.03442)
    # ------------------------------------------------------------------

    def _llm_reflection(
        self,
        generator_fn: callable,
        query: str,
        num_reflections: int = 3,
    ) -> list[str]:
        """Generate reflections by delegating synthesis to a callable.

        Unlike the rule-based `reflect()` method, this uses an external
        generator (typically an LLM) to produce deeper, more abstract
        insights from recalled memories — matching the original Generative
        Agents paper's LLM-driven reflection design.

        Args:
            generator_fn: A callable with signature
                ``generator_fn(memories: list[dict], query: str, num: int)
                -> list[str]``
                that returns reflection strings. The callable receives the
                raw recalled memories and is free to synthesize themes,
                contradictions, and insights via its own logic (LLM, etc.).
            query: The retrieval query that triggered reflection.
            num_reflections: How many reflections to request.

        Returns:
            List of reflection strings produced by the generator.

        Example:
            >>> def llm_summarizer(memories, query, num):
            ...     # Call an actual LLM here
            ...     return [f"LLM insight: {m['content'][:30]}..." for m in memories[:num]]
            >>> reflections = memory._llm_reflection(llm_summarizer, "reinforcement learning", 3)
        """
        memories = self.recall(query, top_k=num_reflections * 3)
        reflections = generator_fn(memories, query, num_reflections)

        # Store reflections internally (same format as reflect())
        timestamp = time.time()
        for r in reflections[:num_reflections]:
            self._reflections.append({
                "content": r,
                "query": query,
                "ts": timestamp,
                "source": "llm_reflection",
            })
        self._last_reflection_time = timestamp
        return reflections[:num_reflections]

    def reflect(self, query: str, num_reflections: int = 3) -> list[str]:
        """Generate reflections from memories (from Generative Agents paper).

        "Reflections are higher-level, more abstract thoughts that
         synthesize and reason over raw memories"

        Enhanced with cross-network synthesis, theme detection,
        contradiction detection, and recurring pattern extraction.
        """
        memories = self.recall(query, top_k=num_reflections * 3)
        reflections = []

        networks_used = set(m.get("network", "") for m in memories)
        high_importance = [m for m in memories if m.get("importance", 0) > 0.7]

        # --- Theme extraction ---
        # Find common words/concepts across recalled memories
        themes = self._extract_themes(memories, top_n=3)
        for theme in themes:
            reflections.append(
                f"Recurring theme: '{theme['word']}' appears in "
                f"{theme['count']} memories related to '{query}' — "
                f"suggesting this is a central concept."
            )

        # --- Contradiction detection ---
        contradictions = self._detect_contradictions(memories)
        for cont in contradictions:
            reflections.append(
                f"Contradiction detected: \"{cont['mem_a'][:60]}...\" "
                f"vs \"{cont['mem_b'][:60]}...\" — "
                f"these represent opposing patterns."
            )

        # --- Cross-network synthesis ---
        if len(networks_used) > 1:
            # Score patterns: what does each network emphasize?
            network_insights = []
            for net in sorted(networks_used):
                net_mems = [m for m in memories if m.get("network") == net]
                if net_mems:
                    avg_imp = sum(m.get("importance", 0) for m in net_mems) / len(net_mems)
                    network_insights.append(
                        f"{net}(avg_imp={avg_imp:.2f},n={len(net_mems)})"
                    )
            reflections.append(
                f"Cross-network synthesis across {len(networks_used)} networks: "
                f"{'; '.join(network_insights)}. "
                f"The '{query}' query draws most from "
                f"{max(networks_used, key=lambda n: sum(1 for m in memories if m.get('network')==n))}."
            )

        # --- High-importance pattern synthesis ---
        if high_importance:
            top_contents = [m["content"][:80] for m in high_importance[:3]]
            summary = "; ".join(top_contents)
            reflections.append(
                f"Synthesized insight from {len(high_importance)} high-importance "
                f"memories: {summary}. "
                f"Pattern: these converge on the core aspects of '{query}'."
            )

        # --- Default single-memory reflections ---
        for i in range(min(num_reflections, len(memories))):
            mem = memories[i]
            reflection = (
                f"[{mem.get('network', 'unknown')}] "
                f"'{mem['content'][:80]}...' "
                f"(importance={mem.get('importance', 0):.2f}, "
                f"relevance={mem.get('relevance', 0):.2f}) — "
                f"relevant to {query} because of shared concepts."
            )
            reflections.append(reflection)

        # Store reflections internally
        timestamp = time.time()
        for r in reflections[:num_reflections]:
            self._reflections.append({
                "content": r,
                "query": query,
                "ts": timestamp,
            })

        self._last_reflection_time = timestamp
        return reflections[:num_reflections + 2]  # a few extra for themes

    def _extract_themes(self, memories: list[dict], top_n: int = 3) -> list[dict]:
        """Extract recurring themes from recalled memories.

        Identifies words that appear with unusually high frequency
        across the memory set, excluding common stopwords.
        """
        stopwords = {
            "the", "a", "an", "is", "was", "were", "are", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "can", "shall",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "above",
            "below", "between", "about", "up", "out", "off", "over",
            "and", "but", "or", "nor", "not", "so", "yet", "both",
            "either", "neither", "this", "that", "these", "those",
            "very", "just", "too", "also", "only", "more", "most",
            "some", "any", "each", "every", "all", "both", "few",
            "own", "same", "other", "another", "such", "which", "what",
            "who", "whom", "whose", "it", "its", "i", "we", "you",
            "he", "she", "they", "me", "him", "her", "us", "them",
        }

        word_counts: Counter = Counter()
        for mem in memories:
            words = mem.get("content", "").lower().split()
            for w in words:
                w = w.strip(".,!?;:'\"()[]{}")
                if w and w not in stopwords and len(w) > 2:
                    word_counts[w] += 1

        if not word_counts:
            return []

        # Return most common words above baseline frequency
        n_memories = max(len(memories), 1)
        themes = []
        for word, count in word_counts.most_common(top_n * 3):
            if count >= max(2, n_memories * 0.2):  # appears in >=20% of memories
                themes.append({"word": word, "count": count})
                if len(themes) >= top_n:
                    break

        return themes

    def _detect_contradictions(self, memories: list[dict]) -> list[dict]:
        """Detect contradictory statements across memories.

        Uses simple negation markers to find contradictions.
        E.g., "is good" vs "is not good" is flagged.
        """
        contradictions = []
        negation_markers = {"not", "never", "no", "cannot", "can't",
                            "doesn't", "doesnt", "isn't", "isnt", "won't",
                            "wont", "don't", "dont", "didn't", "didnt"}

        for i in range(len(memories)):
            for j in range(i + 1, len(memories)):
                words_a = set(memories[i].get("content", "").lower().split())
                words_b = set(memories[j].get("content", "").lower().split())

                # Check if one uses negation words and the other doesn't
                # on the same topic
                common = words_a & words_b - negation_markers
                if len(common) >= 3:
                    has_neg_a = bool(words_a & negation_markers)
                    has_neg_b = bool(words_b & negation_markers)
                    if has_neg_a != has_neg_b:
                        contradictions.append({
                            "mem_a": memories[i].get("content", ""),
                            "mem_b": memories[j].get("content", ""),
                            "common_terms": list(common)[:5],
                        })
                        if len(contradictions) >= 3:
                            return contradictions

        return contradictions

    # ------------------------------------------------------------------
    # LLM Planning (Generative Agents — arXiv 2304.03442)
    # ------------------------------------------------------------------

    def _llm_planning(
        self,
        generator_fn: callable,
        reflections: list[str] | None = None,
        goal: str = "",
        num_plans: int = 3,
    ) -> list[dict]:
        """Generate structured plans by delegating to a callable.

        Unlike the rule-based `plan()` method, this uses an external
        generator (typically an LLM) to produce action plans — matching
        the Generative Agents paper's approach of using LLM to generate
        believable daily plans based on reflections and goals.

        Args:
            generator_fn: A callable with signature
                ``generator_fn(reflections: list[str], goal: str, num: int)
                -> list[dict]``
                Each returned dict must have keys:
                  - goal (str): overarching objective
                  - actions (list[str]): concrete action steps
                  - priority (float): estimated importance 0-1
                  - prerequisites (list[str]): conditions to meet first
            reflections: Reflection strings to base plans on.
                Uses stored reflections if None.
            goal: Optional explicit goal.
            num_plans: Number of plan variants to generate.

        Returns:
            List of structured plan dicts.
        """
        using_reflections = reflections or [
            r["content"] for r in self._reflections[-5:]
        ] or ["General memory consolidation"]

        plans = generator_fn(using_reflections, goal, num_plans)

        # Validate and store plans
        timestamp = time.time()
        validated = []
        for i, p in enumerate(plans[:num_plans]):
            plan = {
                "goal": p.get("goal", goal or "LLM-generated plan"),
                "actions": p.get("actions", ["Review memory patterns"]),
                "priority": max(0.0, min(1.0, p.get("priority", 0.5))),
                "prerequisites": p.get("prerequisites", []),
                "variant": i,
                "num_reflections": len(using_reflections),
                "source": "llm_planning",
            }
            plan["ts"] = timestamp
            self._plans.append(plan)
            validated.append(plan)

        return validated

    # ------------------------------------------------------------------
    # Planning (Generative Agents)
    # ------------------------------------------------------------------

    def plan(self, reflections: list[str] | None = None,
             goal: str = "", num_plans: int = 3) -> list[dict]:
        """Generate action plans based on reflections (from Generative Agents paper).

        Plans are structured sequences of actions derived from current
        reflections and goals. Each plan has:
        - goal: the overarching objective
        - actions: specific steps to achieve the goal
        - priority: estimated importance (0-1)
        - prerequisites: conditions that should be met before execution

        Args:
            reflections: List of reflection strings (uses stored reflections if None).
            goal: Optional goal to focus planning.
            num_plans: Number of plan variants to generate.

        Returns:
            List of plan dicts, each with goal, actions, priority, prerequisites.
        """
        using_reflections = reflections or [
            r["content"] for r in self._reflections[-5:]
        ] or ["General memory consolidation"]

        plans = []

        # Extract key entities and themes from reflections
        key_terms = self._extract_key_terms(using_reflections, top_n=5)

        for i in range(num_plans):
            # Generate plan from reflection patterns
            plan = self._synthesize_plan(
                using_reflections, key_terms, goal, variant=i,
            )
            plans.append(plan)

        # Store plans internally
        timestamp = time.time()
        for p in plans:
            p["ts"] = timestamp
            self._plans.append(p)

        return plans

    def _extract_key_terms(self, texts: list[str], top_n: int = 5) -> list[str]:
        """Extract key terms from reflection texts. Filters stopwords."""
        stopwords = {
            "the", "a", "an", "is", "was", "were", "are", "be", "been",
            "this", "that", "these", "those", "it", "its", "to", "of",
            "in", "for", "on", "with", "at", "by", "from", "and", "but",
            "or", "not", "so", "yet", "very", "just", "too", "also",
        }

        counter: Counter = Counter()
        for text in texts:
            words = text.lower().split()
            for w in words:
                w = w.strip(".,!?;:'\"()[]{}")
                if w and w not in stopwords and len(w) > 3:
                    counter[w] += 1

        return [w for w, _ in counter.most_common(top_n)]

    def _synthesize_plan(self, reflections: list[str], key_terms: list[str],
                         goal: str, variant: int = 0) -> dict:
        """Synthesize a single action plan from reflections and key terms.

        Creates structured plans with:
        - A goal statement derived from reflections
        - 3-5 concrete action steps
        - Priority score based on importance signals in reflections
        - Prerequisites inferred from reflection content
        """
        # Build goal from reflections + explicit goal
        if goal:
            plan_goal = goal
        elif reflections:
            # Extract the most actionable sentence from reflections
            sentences = []
            for r in reflections:
                for s in r.split(". "):
                    s = s.strip()
                    if len(s) > 20 and any(kw in s.lower()
                                            for kw in ["should", "need", "must",
                                                       "recommend", "suggest",
                                                       "plan", "action"]):
                        sentences.append(s)
            plan_goal = sentences[0] if sentences else (
                f"Apply insights from {len(reflections)} reflections"
            )
        else:
            plan_goal = "General memory consolidation and retrieval"

        # Generate action steps based on variant
        base_actions = [
            f"Analyze patterns across memory networks",
            f"Synthesize cross-network insights for key topics",
            f"Validate contradictions between conflicting memories",
            f"Prioritize actions based on importance scores "
            f"({sum(1 for r in reflections if 'importance' in r) if reflections else 0} high-importance signals detected)",
            f"Execute retrieval-augmented query with refined goal: '{plan_goal[:50]}'",
        ]

        # Variant-specific actions
        variant_actions: dict[int, list[str]] = {
            0: [
                f"Conduct deep reflection on {(key_terms[0] if key_terms else 'primary concept')}",
                *base_actions,
                "Evaluate plan effectiveness via simulation",
            ],
            1: [
                *base_actions,
                f"Explore alternative interpretations of {(key_terms[1] if len(key_terms) > 1 else 'secondary concept')}",
                "Benchmark against previous plan outcomes",
            ],
            2: [
                f"Cross-reference {len(reflections)} reflection hypotheses",
                *base_actions,
                "Build composite action from multiple network perspectives",
            ],
        }

        actions = variant_actions.get(variant, base_actions)

        # Priority score based on reflection density and importance signals
        priority = 0.5
        if reflections:
            imp_signals = sum(1 for r in reflections if "importance" in r)
            priority = min(0.3 + imp_signals * 0.15, 1.0)

        # Prerequisites
        prerequisites = []
        if "cross-network" in " ".join(reflections).lower():
            prerequisites.append("Cross-network alignment verified")
        if "contradiction" in " ".join(reflections).lower():
            prerequisites.append("Contradictions resolved")
        if not prerequisites:
            prerequisites.append("Memory retrieval completed")

        return {
            "goal": plan_goal,
            "actions": actions,
            "priority": round(priority, 2),
            "prerequisites": prerequisites,
            "variant": variant,
            "num_reflections": len(reflections),
        }

    # ------------------------------------------------------------------
    # Plan management
    # ------------------------------------------------------------------

    def execute_plan(self, plan_index: int = -1) -> dict:
        """Simulate executing a stored plan.

        Returns a summary of what execution would entail.
        """
        if not self._plans:
            return {"error": "No plans to execute"}

        plan = self._plans[plan_index] if plan_index >= 0 else self._plans[-1]

        return {
            "status": "executed",
            "plan_goal": plan["goal"],
            "actions_taken": len(plan["actions"]),
            "actions": plan["actions"],
            "priority": plan["priority"],
            "plan_id": len(self._plans) - 1 if plan_index < 0 else plan_index,
        }

    def get_reflections(self, limit: int = 10) -> list[dict]:
        """Return stored reflections."""
        return self._reflections[-limit:]

    def get_plans(self, limit: int = 10) -> list[dict]:
        """Return stored plans."""
        return self._plans[-limit:]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        stats = {
            **{name: len(entries) for name, entries in self._networks.items()},
            "total": self._total_retained,
            "unique_tags": len(self._tag_index),
            "reflections": len(self._reflections),
            "plans": len(self._plans),
        }
        # Fix: last_reflection_age can be None, which breaks sum()
        last_age = (
            round(time.time() - self._last_reflection_time, 1)
            if self._last_reflection_time else 0
        )
        stats["last_reflection_age"] = last_age
        return stats
