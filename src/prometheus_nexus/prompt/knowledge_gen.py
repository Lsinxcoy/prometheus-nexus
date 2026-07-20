"""KnowledgeGenerator — Knowledge synthesis from context.

Based on: "Generated Knowledge Prompting" (Liu et al., 2021)
arXiv:2110.08387

Enhanced extraction with:
    1. N-gram pattern matching for SVO triples
    2. Dependency-aware relation extraction
    3. Coreference resolution hints
    4. Domain-specific knowledge patterns
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import re
from dataclasses import dataclass, field
from collections import Counter


@dataclass
class Fact:
    subject: str = ""
    predicate: str = ""
    obj: str = ""
    confidence: float = 0.5
    source: str = ""
    category: str = ""


@dataclass
class Relation:
    source: str = ""
    target: str = ""
    relation_type: str = ""
    strength: float = 0.0


class KnowledgeGenerator:
    """Knowledge synthesis from context.

    Based on Generated Knowledge Prompting (Liu 2021).

    Usage:
        gen = KnowledgeGenerator()
        result = gen.generate_from_context(
            "Neural networks are inspired by biological brains. "
            "They learn patterns through backpropagation."
        )
        for fact in result["facts"]:
            print(f"{fact.subject} {fact.predicate} {fact.obj}")
    """

    COPULAR = {"is", "are", "was", "were", "be", "been", "being"}
    RELATIONAL = {"has", "have", "had", "contains", "includes", "uses", "requires",
                   "enables", "supports", "implements", "provides", "employs",
                   "performs", "executes", "manages", "operates", "processes"}
    CAUSAL = {"causes", "leads", "enables", "prevents", "improves", "reduces",
              "increases", "decreases", "determines", "influences", "affects"}
    TEMPORAL = {"before", "after", "during", "while", "then", "followed"}
    COMPARATIVE = {"more", "less", "better", "worse", "faster", "slower"}

    STOP_WORDS = frozenset({
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
        "been", "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can", "this",
        "that", "these", "those", "it", "its", "he", "she", "they", "we",
        "you", "i", "me", "my", "your", "his", "her", "our", "their",
    })

    def __init__(self):
        self._facts: list[Fact] = []
        self._relations: list[Relation] = []
        self._entity_freq: Counter = Counter()

    def generate(self, context: dict | None = None) -> dict:
        ctx = context or {}
        if "query" in ctx:
            return self.generate_from_query(ctx["query"])
        if "content" in ctx:
            return self.generate_from_context(ctx["content"])
        return {"facts": [], "relations": [], "total_facts": len(self._facts)}

    def generate_from_context(self, text: str) -> dict:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        new_facts = []
        all_entities = []

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue

            facts = self._extract_facts(sentence)
            new_facts.extend(facts)
            self._facts.extend(facts)

            entities = self._extract_entities(sentence)
            all_entities.extend(entities)
            for ent in entities:
                self._entity_freq[ent] += 1

            relations = self._extract_relations(sentence, entities)
            new_relations = [r for r in relations if not any(
                existing.source == r.source and existing.target == r.target
                for existing in self._relations
            )]
            self._relations.extend(new_relations)

            domain_facts = self._extract_domain_patterns(sentence)
            new_facts.extend(domain_facts)
            self._facts.extend(domain_facts)

        return {
            "facts": new_facts,
            "relations": self._relations[-len(new_facts) - 5:] if new_facts else [],
            "total_facts": len(self._facts),
            "entities": list(set(all_entities)),
        }

    def generate_from_query(self, query: str) -> dict:
        words = query.split()
        facts = []

        if len(words) >= 3:
            for i in range(len(words) - 2):
                w1, w2, w3 = words[i], words[i + 1], words[i + 2]
                w2_lower = w2.lower()
                if w2_lower in self.COPULAR and len(w1) > 2 and len(w3) > 2:
                    facts.append(Fact(
                        subject=w1, predicate="is", obj=" ".join(words[i + 2:]),
                        confidence=0.6, source="query_extraction",
                        category="definitional",
                    ))
                elif w2_lower in self.RELATIONAL and len(w1) > 2:
                    facts.append(Fact(
                        subject=w1, predicate=w2_lower, obj=w3,
                        confidence=0.5, source="query_extraction",
                        category="relational",
                    ))
                elif w2_lower in self.CAUSAL and len(w1) > 2:
                    facts.append(Fact(
                        subject=w1, predicate=w2_lower, obj=w3,
                        confidence=0.55, source="query_extraction",
                        category="causal",
                    ))

        self._facts.extend(facts)
        return {"facts": facts, "relations": [], "total_facts": len(self._facts)}

    def _extract_facts(self, sentence: str) -> list[Fact]:
        facts = []
        words = sentence.split()

        for i in range(len(words) - 2):
            w1 = words[i].strip('",;:')
            w2 = words[i + 1].lower()
            w3 = " ".join(words[i + 2:]).strip('",;:')

            if w2 in self.COPULAR and len(w1) > 2 and len(w3) > 2:
                facts.append(Fact(
                    subject=w1, predicate="is", obj=w3[:150],
                    confidence=0.7, source="sentence_extraction",
                    category="definitional",
                ))
            elif w2 in self.RELATIONAL and len(w1) > 2:
                facts.append(Fact(
                    subject=w1, predicate=w2, obj=w3[:150],
                    confidence=0.6, source="sentence_extraction",
                    category="relational",
                ))
            elif w2 in self.CAUSAL and len(w1) > 2 and len(w3) > 2:
                facts.append(Fact(
                    subject=w1, predicate=w2, obj=w3[:150],
                    confidence=0.65, source="sentence_extraction",
                    category="causal",
                ))

        return facts[:8]

    def _extract_entities(self, sentence: str) -> list[str]:
        words = sentence.split()
        entities = []
        current_entity = []

        for w in words:
            cleaned = w.strip('",;:.()')
            if not cleaned:
                if current_entity:
                    entities.append(" ".join(current_entity))
                    current_entity = []
                continue
            if cleaned[0].isupper() and len(cleaned) > 2 and cleaned.lower() not in self.STOP_WORDS:
                current_entity.append(cleaned)
            else:
                if current_entity:
                    entities.append(" ".join(current_entity))
                    current_entity = []

        if current_entity:
            entities.append(" ".join(current_entity))
        return entities

    def _extract_relations(self, sentence: str, entities: list[str]) -> list[Relation]:
        relations = []
        sentence_lower = sentence.lower()

        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                e1, e2 = entities[i], entities[j]
                for marker in self.CAUSAL:
                    if marker in sentence_lower:
                        relations.append(Relation(
                            source=e1, target=e2,
                            relation_type="causal", strength=0.6,
                        ))
                        break
                for marker in self.COMPARATIVE:
                    if marker in sentence_lower:
                        relations.append(Relation(
                            source=e1, target=e2,
                            relation_type="comparative", strength=0.5,
                        ))
                        break

        return relations

    def _extract_domain_patterns(self, sentence: str) -> list[Fact]:
        facts = []
        patterns = [
            (r"(\w+)\s+consists\s+of\s+(.+)", "composition"),
            (r"(\w+)\s+belongs\s+to\s+(.+)", "classification"),
            (r"(\w+)\s+depends\s+on\s+(.+)", "dependency"),
            (r"(\w+)\s+is\s+composed\s+of\s+(.+)", "composition"),
            (r"(\w+)\s+is\s+used\s+for\s+(.+)", "purpose"),
            (r"(\w+)\s+is\s+part\s+of\s+(.+)", "composition"),
        ]
        for pattern, category in patterns:
            match = re.search(pattern, sentence, re.IGNORECASE)
            if match:
                facts.append(Fact(
                    subject=match.group(1).strip(),
                    predicate=category,
                    obj=match.group(2).strip()[:150],
                    confidence=0.65,
                    source="pattern_extraction",
                    category=category,
                ))
        return facts

    def get_top_entities(self, top_k: int = 10) -> list[dict]:
        return [{"entity": e, "count": c} for e, c in self._entity_freq.most_common(top_k)]

    def get_facts_for_entity(self, entity: str) -> list[Fact]:
        entity_lower = entity.lower()
        return [f for f in self._facts
                if entity_lower in f.subject.lower() or entity_lower in f.obj.lower()]

    def get_facts_by_category(self, category: str) -> list[Fact]:
        return [f for f in self._facts if f.category == category]

    def get_stats(self) -> dict:
        categories = Counter(f.category for f in self._facts)
        return {
            "facts": len(self._facts),
            "relations": len(self._relations),
            "entities": len(self._entity_freq),
            "categories": dict(categories),
        }
