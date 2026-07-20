"""
SemanticLearner - Semantic Learning Engine with Performance Optimizations

Core Problem:
Current system only supports parameter-based learning (KnowledgeToMechanism),
cannot handle concept relationships, causal relationships, comparative relationships, etc.

Solution: Three-layer architecture for semantic understanding:
Level A: Parameter extraction (existing KnowledgeToMechanism)
Level B: Strategy/pattern extraction
Level C: Conceptual knowledge graph with inference rules and performance optimizations

Author: Prometheus Ultra Team
Version: 2.1.0
"""
from __future__ import annotations
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Any, defaultdict
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class Concept:
    """A concept extracted from text."""
    name: str
    category: str = "general"
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.6
    source: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class Relation:
    """A relation between two concepts."""
    source_concept: str
    target_concept: str
    relation_type: str
    strength: float = 0.5
    evidence: str = ""
    confidence: float = 0.6
    created_at: float = field(default_factory=time.time)


class ConceptExtractor:
    """Level 1: Extract concepts using pattern matching and domain knowledge."""
    
    # Domain-specific patterns
    DOMAIN_PATTERNS = {
        "ml": [
            r"\b(Transformer|RNN|CNN|LSTM|GRU)\b",
            r"\b(neural network|deep learning|machine learning)\b",
            r"\b(backpropagation|gradient descent|optimization)\b",
        ],
        "software": [
            r"\b(API|SDK|framework|library)\b",
            r"\b(microservice|container|docker|kubernetes)\b",
        ],
        "general": [
            r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b",
        ],
    }
    
    def extract(self, text: str) -> list[Concept]:
        """Extract concepts from text with improved multi-word entity matching."""
        concepts = []
        text_lower = text.lower()
        
        # Multi-word technical terms (ordered by length for priority)
        multi_word_terms = [
            "Neural Network", "Deep Learning", "Machine Learning",
            "Multi-head Attention", "Self-attention", "Cross-attention",
            "Backpropagation", "Gradient Descent", "Vanishing Gradient",
            "Long Short-Term Memory", "Recurrent Neural Network",
            "Convolutional Neural Network", "Generative Adversarial Network",
            "Transformer", "Attention Mechanism", "Positional Encoding",
            "Word Embedding", "Feature Extraction", "Transfer Learning",
        ]
        
        # Single-word technical terms
        single_word_terms = [
            "RNN", "CNN", "LSTM", "GRU", "Attention", "Optimizer",
            "Loss Function", "Activation", "Layer", "Parameter",
            "Training", "Inference", "Model", "Architecture",
            "Gradient", "Epoch", "Batch", "Learning Rate",
        ]
        
        # Extract all entities
        entities = set()
        
        # Add multi-word terms if found
        for term in multi_word_terms:
            if term.lower() in text_lower:
                entities.add(term)
        
        # Add single-word terms if found
        for term in single_word_terms:
            if term.lower() in text_lower:
                entities.add(term)
        
        # Also extract capitalized words as potential entities
        capitalized = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        for word in capitalized:
            if len(word) >= 3 and word not in entities:
                entities.add(word)
        
        # Plural forms mapping
        plural_map = {
            "neural networks": "Neural Network",
            "architectures": "Architecture",
            "models": "Model",
            "layers": "Layer",
            "parameters": "Parameter",
            "attentions": "Attention",
        }
        for plural, singular in plural_map.items():
            if plural in text_lower:
                entities.add(singular)
        
        for entity in entities:
            if len(entity) < 3:
                continue
            
            # Determine category based on context
            category = self._classify_entity(entity, text_lower)
            
            concepts.append(Concept(
                name=entity,
                category=category,
                confidence=0.65,  # Slightly higher for explicit matches
                source="semantic_extraction"
            ))
        
        return concepts
    
    def _classify_entity(self, entity: str, text_lower: str) -> str:
        """Classify entity into categories."""
        entity_lower = entity.lower()
        
        if any(w in entity_lower for w in ["network", "nn", "transformer"]):
            return "architecture"
        if any(w in entity_lower for w in ["learning", "training", "inference"]):
            return "process"
        if any(w in entity_lower for w in ["gradient", "loss", "optimizer"]):
            return "parameter"
        if any(w in entity_lower for w in ["attention", "embedding", "layer"]):
            return "component"
        
        return "general"


class RelationExtractor:
    """Level 2: Extract relations between concepts using pattern matching."""
    
    def extract(self, text: str, concepts: list[Concept]) -> list[Relation]:
        """Extract relations from text."""
        relations = []
        text_lower = text.lower()
        
        # Build concept name mapping (multiple forms)
        concept_names = {}
        for c in concepts:
            # Store multiple forms
            concept_names[c.name] = c
            concept_names[c.name.lower()] = c
            # Also store title case variants
            if c.name != c.name.title():
                concept_names[c.name.title()] = c
        
        # Check each pattern
        for rel_type, patterns in self._get_patterns().items():
            for pattern in patterns:
                matches = re.finditer(pattern, text_lower)
                for match in matches:
                    source_name = match.group(1).strip()
                    target_name = match.group(2).strip()
                    
                    # Try to match source and target
                    source_concept = None
                    target_concept = None
                    
                    # Source: try exact match first
                    if source_name in concept_names:
                        source_concept = concept_names[source_name]
                    elif source_name.title() in concept_names:
                        source_concept = concept_names[source_name.title()]
                    
                    # Target: try partial matching for multi-word entities
                    target_words = target_name.split()
                    best_match = None
                    best_len = 0
                    
                    for concept_name in concept_names:
                        if concept_name.lower() in target_name.lower():
                            if len(concept_name) > best_len:
                                best_match = concept_name
                                best_len = len(concept_name)
                    
                    if best_match:
                        target_concept = concept_names[best_match]
                    elif target_name in concept_names:
                        target_concept = concept_names[target_name]
                    elif target_name.title() in concept_names:
                        target_concept = concept_names[target_name.title()]
                    
                    if source_concept and target_concept:
                        rel = Relation(
                            source_concept=source_concept.name,
                            target_concept=target_concept.name,
                            relation_type=rel_type,
                            strength=0.6,
                            evidence=match.group(0),
                            confidence=0.7,
                        )
                        relations.append(rel)
        
        return relations
    
    def _get_patterns(self) -> dict[str, list[str]]:
        """Get all relation patterns."""
        return {
            "is_a": [
                r"(\w+(?:\s+\w+)*)\s+is\s+a\s+(\w+(?:\s+\w+)*)",
                r"(\w+(?:\s+\w+)*)\s+is\s+an\s+(\w+(?:\s+\w+)*)",
                r"(\w+(?:\s+\w+)*)\s+is\s+the\s+(\w+(?:\s+\w+)*)",
                r"(\w+)\s+is\s+a\s+type\s+of\s+(\w+)",
                r"(\w+)\s+is\s+a\s+kind\s+of\s+(\w+)",
            ],
            "has_part": [
                r"(\w+(?:\s+\w+)*)\s+has\s+(\w+(?:\s+\w+)*)",
                r"(\w+(?:\s+\w+)*)\s+contains\s+(\w+(?:\s+\w+)*)",
                r"(\w+(?:\s+\w+)*)\s+includes\s+(\w+(?:\s+\w+)*)",
                r"(\w+)\s+composed\s+of\s+(\w+)",
                r"(\w+)\s+made\s+of\s+(\w+)",
            ],
            "causes": [
                r"(\w+(?:\s+\w+)*)\s+causes\s+(\w+(?:\s+\w+)*)",
                r"(\w+(?:\s+\w+)*)\s+leads\s+to\s+(\w+(?:\s+\w+)*)",
                r"(\w+(?:\s+\w+)*)\s+results\s+in\s+(\w+(?:\s+\w+)*)",
                r"(\w+)\s+because\s+of\s+(\w+)",
                r"(\w+)\s+due\s+to\s+(\w+)",
            ],
            "better_than": [
                r"(\w+(?:\s+\w+)*)\s+is\s+better\s+than\s+(\w+(?:\s+\w+)*)",
                r"(\w+(?:\s+\w+)*)\s+outperforms\s+(\w+(?:\s+\w+)*)",
                r"(\w+(?:\s+\w+)*)\s+surpasses\s+(\w+(?:\s+\w+)*)",
                r"(\w+)\s+more\s+effective\s+than\s+(\w+)",
                r"(\w+)\s+more\s+efficient\s+than\s+(\w+)",
            ],
            "before": [
                r"(\w+(?:\s+\w+)*)\s+before\s+(\w+(?:\s+\w+)*)",
                r"(\w+(?:\s+\w+)*)\s+after\s+(\w+(?:\s+\w+)*)",
                r"(\w+)\s+followed\s+by\s+(\w+)",
            ],
            "requires": [
                r"(\w+(?:\s+\w+)*)\s+requires\s+(\w+(?:\s+\w+)*)",
                r"(\w+(?:\s+\w+)*)\s+needs\s+(\w+(?:\s+\w+)*)",
                r"(\w+)\s+depends\s+on\s+(\w+)",
            ],
        }


class KnowledgeGraphBuilder:
    """Build and manage a knowledge graph with performance optimizations."""
    
    def __init__(self):
        self.concepts: dict[str, Concept] = {}
        self.relations: list[Relation] = []
        self.adjacency: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        # Performance optimizations
        self._concept_index: dict[str, int] = {}  # name -> index for fast lookup
        self._relation_cache: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        self._last_updated: float = 0
        self._version: int = 0
    
    def add_concept(self, concept: Concept) -> None:
        """Add a concept to the graph with indexing."""
        if concept.name not in self._concept_index:
            self._concept_index[concept.name] = len(self.concepts)
        self.concepts[concept.name] = concept
        self._last_updated = time.time()
        self._version += 1
    
    def add_relation(self, relation: Relation) -> None:
        """Add a relation to the graph with caching."""
        self.relations.append(relation)
        self.adjacency[relation.source_concept].append((relation.target_concept, relation.relation_type, relation.strength))
        # Update cache
        self._relation_cache[relation.source_concept].append((relation.target_concept, relation.relation_type, relation.strength))
        self._last_updated = time.time()
        self._version += 1
    
    def get_related(self, concept_name: str, relation_type: str | None = None) -> list[tuple[str, float]]:
        """Get related concepts with caching."""
        # Check cache first
        if concept_name in self._relation_cache:
            results = []
            for target, rel_type, strength in self._relation_cache[concept_name]:
                if relation_type is None or rel_type == relation_type:
                    results.append((target, strength))
            return results
        
        # Fallback to direct access
        results = []
        for target, rel_type, strength in self.adjacency.get(concept_name, []):
            if relation_type is None or rel_type == relation_type:
                results.append((target, strength))
        return results
    
    def transitive_closure(self, concept_name: str, max_depth: int = 3) -> set[str]:
        """Compute transitive closure with BFS and early termination."""
        visited = set()
        queue = [(concept_name, 0)]
        
        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited.add(current)
            
            # Use cached relations for faster access
            for target, _, _ in self._relation_cache.get(current, []):
                if target not in visited:
                    queue.append((target, depth + 1))
        
        return visited
    
    def find_paths(self, start: str, end: str, max_length: int = 5) -> list[list[tuple[str, str]]]:
        """Find all paths between two concepts with DFS and pruning."""
        results = []
        
        def dfs(current: str, path: list[tuple[str, str]], depth: int):
            if depth > max_length:
                return
            if current == end:
                results.append(path[:])
                return
            
            # Prune if already found many paths
            if len(results) >= 100:
                return
            
            for target, rel_type, strength in self._relation_cache.get(current, []):
                if target not in [p[0] for p in path]:  # Avoid cycles
                    path.append((target, rel_type))
                    dfs(target, path, depth + 1)
                    path.pop()
        
        dfs(start, [(start, "start")], 0)
        return results
    
    def infer_property(self, concept: str, property_name: str) -> Any:
        """Infer a property of a concept based on its relations."""
        # Example: If X is_a Y and Y has_part Z, then X has_part Z
        related = self.get_related(concept, "is_a")
        for target, strength in related:
            # Get parts of the parent
            parts = self.get_related(target, "has_part")
            for part_name, part_strength in parts:
                # Inherit the relation with reduced confidence
                if part_name not in [r[0] for r in self.adjacency.get(concept, [])]:
                    self.adjacency[concept].append((part_name, "has_part", strength * 0.8))
                    self._relation_cache[concept].append((part_name, "has_part", strength * 0.8))
        
        return None
    
    def get_subgraph(self, concept: str, max_depth: int = 2) -> dict:
        """Get a subgraph centered around a concept."""
        visited = self.transitive_closure(concept, max_depth)
        
        subgraph = {
            "center": concept,
            "concepts": list(visited),
            "edges": [],
        }
        
        for c in visited:
            for target, rel_type, strength in self.adjacency.get(c, []):
                if target in visited:
                    subgraph["edges"].append({
                        "source": c,
                        "target": target,
                        "type": rel_type,
                        "strength": strength,
                    })
        
        return subgraph
    
    def find_pattern(self, pattern: list[str]) -> list[list[str]]:
        """Find paths matching a pattern of relation types."""
        results = []
        
        for start in self.concepts:
            path = self._find_path(start, pattern, 0)
            if path:
                results.append(path)
        
        return results
    
    def _find_path(self, current: str, pattern: list[str], index: int) -> list[str] | None:
        """Recursively find a path matching the pattern."""
        if index == len(pattern):
            return [current]
        
        rel_type = pattern[index]
        for target, r_type, _ in self.adjacency.get(current, []):
            if r_type == rel_type:
                path = self._find_path(target, pattern, index + 1)
                if path:
                    return [current] + path
        
        return None
    
    def get_stats(self) -> dict:
        """Get statistics about the knowledge graph."""
        return {
            "concepts": len(self.concepts),
            "relations": len(self.relations),
            "version": self._version,
            "last_updated": self._last_updated,
        }
    
    def clear_cache(self) -> None:
        """Clear the relation cache."""
        self._relation_cache.clear()
    
    def rebuild_cache(self) -> None:
        """Rebuild the relation cache from scratch."""
        self._relation_cache.clear()
        for source, targets in self.adjacency.items():
            self._relation_cache[source] = list(targets)


class InferenceEngine:
    """Apply inference rules to derive new relations."""
    
    def __init__(self, graph_builder: KnowledgeGraphBuilder):
        self.graph = graph_builder
    
    def apply_rules(self, concepts: list[Concept], relations: list[Relation]) -> list[Relation]:
        """Apply inference rules to derive new relations."""
        inferred = []
        
        # Rule 1: Transitivity of is_a relation
        # If A is_a B and B is_a C, then A is_a C
        for rel1 in self.graph.relations:
            if rel1.relation_type == "is_a":
                for rel2 in self.graph.relations:
                    if rel2.relation_type == "is_a" and rel2.source_concept == rel1.target_concept:
                        inferred_rel = Relation(
                            source_concept=rel1.source_concept,
                            target_concept=rel2.target_concept,
                            relation_type="is_a",
                            strength=min(rel1.strength, rel2.strength) * 0.9,
                            evidence=f"Inferred: {rel1.source_concept} -> {rel1.target_concept} -> {rel2.target_concept}",
                            confidence=0.7,
                        )
                        inferred.append(inferred_rel)
        
        # Rule 2: Property inheritance
        # If A is_a B and B has_part C, then A has_part C
        for rel1 in self.graph.relations:
            if rel1.relation_type == "is_a":
                for rel2 in self.graph.relations:
                    if rel2.relation_type == "has_part" and rel2.source_concept == rel1.target_concept:
                        inferred_rel = Relation(
                            source_concept=rel1.source_concept,
                            target_concept=rel2.target_concept,
                            relation_type="has_part",
                            strength=min(rel1.strength, rel2.strength) * 0.8,
                            evidence=f"Inherited: {rel1.source_concept} inherits {rel2.target_concept} from {rel1.target_concept}",
                            confidence=0.6,
                        )
                        inferred.append(inferred_rel)
        
        # Rule 3: Causal chain
        # If A causes B and B causes C, then A causes C
        for rel1 in self.graph.relations:
            if rel1.relation_type == "causes":
                for rel2 in self.graph.relations:
                    if rel2.relation_type == "causes" and rel2.source_concept == rel1.target_concept:
                        inferred_rel = Relation(
                            source_concept=rel1.source_concept,
                            target_concept=rel2.target_concept,
                            relation_type="causes",
                            strength=min(rel1.strength, rel2.strength) * 0.7,
                            evidence=f"Chain: {rel1.source_concept} -> {rel1.target_concept} -> {rel2.target_concept}",
                            confidence=0.5,
                        )
                        inferred.append(inferred_rel)
        
        return inferred


class IncrementalLearner:
    """Incremental learning with knowledge updates."""
    
    def __init__(self, graph_builder: KnowledgeGraphBuilder):
        self.graph = graph_builder
        self.update_history: list[dict] = []
    
    def update_knowledge(self, content: str, source: str = "incremental") -> dict:
        """Update knowledge incrementally."""
        stats = self.graph.get_stats()
        
        # Record update
        self.update_history.append({
            "timestamp": time.time(),
            "source": source,
            "content_length": len(content),
            "current_stats": stats,
        })
        
        # Keep only last 100 updates
        if len(self.update_history) > 100:
            self.update_history = self.update_history[-100:]
        
        return {
            "updated": True,
            "history_size": len(self.update_history),
            "current_stats": stats,
        }
    
    def get_learning_rate(self) -> float:
        """Get adaptive learning rate based on history."""
        if len(self.update_history) < 10:
            return 0.1
        
        # Reduce learning rate if recent updates are frequent
        recent_intervals = [h["timestamp"] - self.update_history[i-1]["timestamp"]
                          for i, h in enumerate(self.update_history[-10:]) if i > 0]
        
        if not recent_intervals:
            return 0.1
        
        avg_interval = sum(recent_intervals) / len(recent_intervals)
        
        # More frequent updates → lower learning rate
        if avg_interval < 300:  # Less than 5 minutes
            return 0.05
        elif avg_interval < 1800:  # Less than 30 minutes
            return 0.1
        else:
            return 0.2


class SemanticLearner:
    """Main semantic learning engine with incremental learning and inference rules."""
    
    def __init__(self):
        self.concept_extractor = ConceptExtractor()
        self.relation_extractor = RelationExtractor()
        self.graph_builder = KnowledgeGraphBuilder()
        self.inference_engine = InferenceEngine(self.graph_builder)
        self.incremental_learner = IncrementalLearner(self.graph_builder)
    
    def learn(self, content: str, tags: list[str] | None = None) -> dict:
        """Learn from content and extract semantic structure."""
        tags = tags or []
        
        # Level 1: Extract concepts
        concepts = self.concept_extractor.extract(content)
        for concept in concepts:
            self.graph_builder.add_concept(concept)
        
        # Level 2: Extract relations
        relations = self.relation_extractor.extract(content, concepts)
        for relation in relations:
            self.graph_builder.add_relation(relation)
        
        # Level 3: Apply inference rules
        inferred_relations = self.inference_engine.apply_rules(concepts, relations)
        for relation in inferred_relations:
            self.graph_builder.add_relation(relation)
        
        # Return summary
        return {
            "concepts_found": len(concepts),
            "relations_found": len(relations),
            "inferred_relations": len(inferred_relations),
            "concepts": [c.name for c in concepts],
            "relations": [
                {
                    "source": r.source_concept,
                    "target": r.target_concept,
                    "type": r.relation_type,
                    "strength": r.strength,
                }
                for r in relations
            ],
            "inferred": [
                {
                    "source": r.source_concept,
                    "target": r.target_concept,
                    "type": r.relation_type,
                    "strength": r.strength,
                }
                for r in inferred_relations
            ],
        }
    
    def query(self, concept: str, relation_type: str | None = None) -> list[dict]:
        """Query the knowledge graph."""
        related = self.graph_builder.get_related(concept, relation_type)
        return [{"concept": c, "strength": s} for c, s in related]
    
    def reason(self, concept: str, max_depth: int = 3) -> set[str]:
        """Reason about reachable concepts."""
        return self.graph_builder.transitive_closure(concept, max_depth)
    
    def get_stats(self) -> dict:
        """Get statistics about the knowledge graph."""
        relation_counts = defaultdict(int)
        for r in self.graph_builder.relations:
            relation_counts[r.relation_type] += 1
        
        return {
            "concepts": len(self.graph_builder.concepts),
            "relations": len(self.graph_builder.relations),
            "relation_types": dict(relation_counts),
        }
    
    def save_to_file(self, filepath: str) -> None:
        """Save knowledge graph to JSON file."""
        import json
        
        data = {
            "concepts": [
                {
                    "name": c.name,
                    "category": c.category,
                    "properties": c.properties,
                    "confidence": c.confidence,
                    "source": c.source,
                    "created_at": c.created_at,
                }
                for c in self.graph_builder.concepts.values()
            ],
            "relations": [
                {
                    "source": r.source_concept,
                    "target": r.target_concept,
                    "relation_type": r.relation_type,
                    "strength": r.strength,
                    "evidence": r.evidence,
                    "confidence": r.confidence,
                    "created_at": r.created_at,
                }
                for r in self.graph_builder.relations
            ],
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info("Knowledge graph saved to %s", filepath)
    
    def load_from_file(self, filepath: str) -> None:
        """Load knowledge graph from JSON file."""
        import json
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Clear existing data
            self.graph_builder.concepts.clear()
            self.graph_builder.relations.clear()
            self.graph_builder.adjacency.clear()
            
            # Load concepts
            for c_data in data.get("concepts", []):
                concept = Concept(
                    name=c_data["name"],
                    category=c_data.get("category", ""),
                    properties=c_data.get("properties", {}),
                    confidence=c_data.get("confidence", 0.6),
                    source=c_data.get("source", ""),
                    created_at=c_data.get("created_at", time.time()),
                )
                self.graph_builder.add_concept(concept)
            
            # Load relations
            for r_data in data.get("relations", []):
                relation = Relation(
                    source_concept=r_data["source"],
                    target_concept=r_data["target"],
                    relation_type=r_data["relation_type"],
                    strength=r_data.get("strength", 0.5),
                    evidence=r_data.get("evidence", ""),
                    confidence=r_data.get("confidence", 0.6),
                    created_at=r_data.get("created_at", time.time()),
                )
                self.graph_builder.add_relation(relation)
            
            logger.info("Knowledge graph loaded from %s", filepath)
        except FileNotFoundError:
            logger.warning("Knowledge graph file not found: %s", filepath)
        except Exception as e:
            logger.error("Failed to load knowledge graph: %s", e)