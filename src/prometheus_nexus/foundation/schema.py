"""Foundation schema — complete type system for Prometheus Ultra.

Fused from:
- Z:\Prometheus Ω: 42 NodeType + 40 EdgeType + 15-dim MemoryEntry
- Genesis: extended gate types + evolution types
- Omega-Omega: branch system + write tokens

Note: This module defines the core type system (enums + dataclasses) used
across all Prometheus Ultra subsystems. It has NO specific arXiv paper
dependency — the types are fused from internal Omega codebase conventions
and project-wide design requirements. All algorithmic references (search,
evolution, memory, etc.) belong in their respective implementation modules.
For arXiv-backed components, see:
  - Verbatim Chunks (2601.00821) → raw_chunk field on Node
  - PolarMem (2602.00415) → trust_state field on Node
  - Grokers (2606.00050) → chunk-structural fields on Node
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


def generate_uuidv7() -> str:
    ts_ms = int(time.time() * 1000)
    raw = uuid.uuid4().bytes
    ts_bytes = ts_ms.to_bytes(6, "big")
    result = bytes([ts_bytes[0], ts_bytes[1], ts_bytes[2], ts_bytes[3],
                    ts_bytes[4], ts_bytes[5]]) + raw[6:]
    return uuid.UUID(bytes=result).hex


# ============================================================
# Core Enums
# ============================================================

class NodeType(Enum):
    FACT = "FACT"
    RULE = "RULE"
    GOAL = "GOAL"
    EPISODE = "EPISODE"
    CONCEPT = "CONCEPT"
    BELIEF = "BELIEF"
    HYPOTHESIS = "HYPOTHESIS"
    EVENT = "EVENT"
    ENTITY = "ENTITY"
    RELATION = "RELATION"
    PROCEDURE = "PROCEDURE"
    CONSTRAINT = "CONSTRAINT"
    METRIC = "METRIC"
    SKILL = "SKILL"
    TOOL = "TOOL"
    AGENT = "AGENT"
    ORGAN = "ORGAN"
    MEMORY_TRACE = "MEMORY_TRACE"
    EXPERIENCE = "EXPERIENCE"
    INSIGHT = "INSIGHT"
    PATTERN = "PATTERN"
    ANOMALY = "ANOMALY"
    REWARD = "REWARD"
    PUNISHMENT = "PUNISHMENT"
    FEEDBACK = "FEEDBACK"
    DREAM = "DREAM"
    REFLECTION = "REFLECTION"
    CONSOLIDATED = "CONSOLIDATED"
    ARCHIVED = "ARCHIVED"
    FRAGILE = "FRAGILE"
    ROBUST = "ROBUST"
    EVOLVING = "EVOLVING"
    STABLE = "STABLE"
    DEAD = "DEAD"
    ZOMBIE = "ZOMBIE"
    MUTANT = "MUTANT"
    HYBRID = "HYBRID"
    SYNTHETIC = "SYNTHETIC"
    BRIDGED = "BRIDGED"
    CAUSAL = "CAUSAL"
    TEMPORAL = "TEMPORAL"
    SPATIAL = "SPATIAL"
    PAPER = "PAPER"          # 外部论文(arxiv/academic/report) — T4 编译源
    PROJECT = "PROJECT"      # 外部开源项目(github) — T3 提取源


class EdgeType(Enum):
    SEMANTIC_SIMILAR = "SEMANTIC_SIMILAR"
    CAUSAL_CAUSES = "CAUSAL_CAUSES"
    CAUSAL_PREVENTS = "CAUSAL_PREVENTS"
    TEMPORAL_BEFORE = "TEMPORAL_BEFORE"
    TEMPORAL_AFTER = "TEMPORAL_AFTER"
    TEMPORAL_DURING = "TEMPORAL_DURING"
    LOGICAL_IMPLIES = "LOGICAL_IMPLIES"
    LOGICAL_CONTRADICTS = "LOGICAL_CONTRADICTS"
    LOGICAL_EQUIVALENT = "LOGICAL_EQUIVALENT"
    HIERARCHY_PARENT = "HIERARCHY_PARENT"
    HIERARCHY_CHILD = "HIERARCHY_CHILD"
    HIERARCHY_PART_OF = "HIERARCHY_PART_OF"
    ASSOCIATION_CO_OCCURS = "ASSOCIATION_CO_OCCURS"
    ASSOCIATION_FREQ_USED = "ASSOCIATION_FREQ_USED"
    ASSOCIATION_RARE = "ASSOCIATION_RARE"
    EVOLUTION_MUTATED = "EVOLUTION_MUTATED"
    EVOLUTION_CROSSOVER = "EVOLUTION_CROSSOVER"
    EVOLUTION_REVERTED = "EVOLUTION_REVERTED"
    EVOLUTION_SPECIATED = "EVOLUTION_SPECIATED"
    MEMORY_CONSOLIDATED = "MEMORY_CONSOLIDATED"
    MEMORY_FORGOTTEN = "MEMORY_FORGOTTEN"
    MEMORY_PROMOTED = "MEMORY_PROMOTED"
    MEMORY_DEMOTED = "MEMORY_DEMOTED"
    SKILL_DEPENDS_ON = "SKILL_DEPENDS_ON"
    SKILL_CONFLICTS_WITH = "SKILL_CONFLICTS_WITH"
    AGENT_COLLABORATES = "AGENT_COLLABORATES"
    AGENT_COMPETES = "AGENT_COMPETES"
    AGENT_DELEGATES = "AGENT_DELEGATES"
    BELIEF_SUPPORTS = "BELIEF_SUPPORTS"
    BELIEF_REFUTES = "BELIEF_REFUTES"
    BELIEF_STRENGTHENS = "BELIEF_STRENGTHENS"
    FEEDBACK_POSITIVE = "FEEDBACK_POSITIVE"
    FEEDBACK_NEGATIVE = "FEEDBACK_NEGATIVE"
    FEEDBACK_CORRECTIVE = "FEEDBACK_CORRECTIVE"
    FEEDBACK_REINFORCE = "FEEDBACK_REINFORCE"
    CROSS_AGENT_BORROWED = "CROSS_AGENT_BORROWED"
    CROSS_AGENT_SHARED = "CROSS_AGENT_SHARED"
    CROSS_AGENT_DERIVED = "CROSS_AGENT_DERIVED"
    PROVENANCE_DERIVED_FROM = "PROVENANCE_DERIVED_FROM"


class MemoryTier(Enum):
    WORKING = 0
    SHORT_TERM = 1
    LONG_TERM = 2
    EPISODIC = 3
    SEMANTIC = 4
    PROCEDURAL = 5
    ARCHIVE = 6


class MemoryLayer(Enum):
    L0_STORE = "L0_STORE"
    L1_INDEX = "L1_INDEX"
    L2_SEARCH = "L2_SEARCH"
    L3_RETRIEVE = "L3_RETRIEVE"
    L4_LIFECYCLE = "L4_LIFECYCLE"
    L5_EVOLUTION = "L5_EVOLUTION"
    L6_ORGANS = "L6_ORGANS"
    L7_SAFETY = "L7_SAFETY"
    L8_GOVERNANCE = "L8_GOVERNANCE"
    L9_MONITORING = "L9_MONITORING"
    L10_COLLABORATION = "L10_COLLABORATION"
    L11_ECOSYSTEM = "L11_ECOSYSTEM"


class TrustLevel(Enum):
    UNTRUSTED = "UNTRUSTED"
    BASIC = "BASIC"
    VERIFIED = "VERIFIED"
    PRIVILEGED = "PRIVILEGED"
    ROOT = "ROOT"


class AutonomyLevel(Enum):
    L0_MANUAL = "L0_MANUAL"
    L1_ASSISTED = "L1_ASSISTED"
    L2_SUPERVISED = "L2_SUPERVISED"
    L3_AUTONOMOUS = "L3_AUTONOMOUS"
    L4_FULL = "L4_FULL"


class SecurityPosture(Enum):
    MINIMAL = "MINIMAL"
    STANDARD = "STANDARD"
    HARDENED = "HARDENED"
    FORTRESS = "FORTRESS"


class EvolutionDirection(Enum):
    FORWARD = "FORWARD"
    LATERAL = "LATERAL"
    BACKWARD = "BACKWARD"
    STAGNANT = "STAGNANT"


class LifecycleAction(Enum):
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    CONSOLIDATE = "CONSOLIDATE"
    FORGET = "FORGET"
    PROMOTE = "PROMOTE"
    DEMOTE = "DEMOTE"
    BRIDGE = "BRIDGE"
    EVOLVE = "EVOLVE"


class GateResult(Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"
    CRITICAL = "CRITICAL"


class CommitState(Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"
    CONFLICT = "CONFLICT"


class ProvenanceType(Enum):
    DIRECT_OBSERVATION = "DIRECT_OBSERVATION"
    INFERENCE = "INFERENCE"
    TESTIMONY = "TESTIMONY"
    AGGREGATION = "AGGREGATION"
    SYNTHESIS = "SYNTHESIS"
    RETRIEVAL = "RETRIEVAL"
    CREATION = "CREATION"
    EXTERNAL = "EXTERNAL"


class ConstraintKind(Enum):
    CARDINALITY = "CARDINALITY"
    TYPE = "TYPE"
    RANGE = "RANGE"
    DEPENDENCY = "DEPENDENCY"
    INVARIANT = "INVARIANT"


class WriteOperator(Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    MERGE = "MERGE"


class Strictness(Enum):
    STRICT = "STRICT"
    FUZZY = "FUZZY"
    RELAXED = "RELAXED"


class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class GraderType(Enum):
    BINARY = "BINARY"
    CONTINUOUS = "CONTINUOUS"
    RANKING = "RANKING"


class EvolutionResult(Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    BLOCKED = "BLOCKED"
    DEGRADED = "DEGRADED"
    NOOP = "NOOP"


class MemoryScope(Enum):
    LOCAL = "LOCAL"
    SHARED = "SHARED"
    GLOBAL = "GLOBAL"


class FailureMode(Enum):
    NONE = "NONE"
    TIMEOUT = "TIMEOUT"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    LOGIC_ERROR = "LOGIC_ERROR"
    EXTERNAL_FAILURE = "EXTERNAL_FAILURE"
    CORRUPTION = "CORRUPTION"


class AlertLevel(Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


class LoopState(Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"


# ============================================================
# Data Classes
# ============================================================

@dataclass
class WeibullParams:
    shape: float = 1.5
    scale: float = 100.0
    min_retention: float = 0.05


@dataclass
class Node:
    id: str = ""
    type: NodeType = NodeType.FACT
    content: str = ""
    utility: float = 0.5
    surprise: float = 0.0
    tags: list[str] = field(default_factory=list)
    branch: str = "main"
    source: ProvenanceType = ProvenanceType.DIRECT_OBSERVATION
    confidence: float = 0.5
    created_at: float = 0.0
    updated_at: float = 0.0
    access_count: int = 0
    tier: MemoryTier = MemoryTier.WORKING
    weibull_params: WeibullParams = field(default_factory=WeibullParams)
    tx_from: float = 0.0
    tx_to: float = 0.0
    version: int = 1
    # Verbatim Chunks 2601.00821 / PolarMem 2602.00415 / Grokers 2606.00050
    raw_chunk: str = ""  # Original verbatim chunk (Verbatim Chunks 2601.00821)
    trust_state: str = "unknown"  # PolarMem 2602.00415 tristate: "has"/"not_has"/"uncertain"
    url: str = ""  # 源地址(外部知识: arxiv/github/wiki URL), 供T3/T4下游消费不重拉

    def __post_init__(self):
        if not self.id:
            self.id = generate_uuidv7()
        now = time.time()
        if self.created_at == 0.0:
            self.created_at = now
        if self.updated_at == 0.0:
            self.updated_at = now

    def touch(self):
        self.access_count += 1
        self.updated_at = time.time()


@dataclass
class Edge:
    source_id: str = ""
    target_id: str = ""
    type: EdgeType = EdgeType.SEMANTIC_SIMILAR
    weight: float = 1.0
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()


@dataclass
class Constraint:
    kind: ConstraintKind = ConstraintKind.CARDINALITY
    strictness: Strictness = Strictness.STRICT
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Provenance:
    type: ProvenanceType = ProvenanceType.DIRECT_OBSERVATION
    source: str = ""
    timestamp: float = 0.0
    confidence: float = 0.5
    chain: list[str] = field(default_factory=list)


@dataclass
class NodeFeedback:
    node_id: str = ""
    feedback_type: str = ""
    value: float = 0.0
    timestamp: float = 0.0


@dataclass
class FailureLog:
    action: str = ""
    error: str = ""
    timestamp: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)


# ============================================================
# Gate / Result Types
# ============================================================

@dataclass
class GateCheckResult:
    passed: bool = True
    gate_name: str = ""
    reason: str = ""
    score: float = 1.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class WriteGateResult:
    passed: bool = True
    write_id: str = ""
    reason: str = ""
    token: str = ""


@dataclass
class LifecycleDecision:
    action: LifecycleAction = LifecycleAction.CREATE
    passed: bool = True
    reason: str = ""


@dataclass
class EvolutionCheckResult:
    passed: bool = True
    verdict: Any = None
    reason: str = ""
    score: float = 0.0


@dataclass
class VerificationResult:
    passed: bool = True
    reason: str = ""
    confidence: float = 0.0


@dataclass
class HookResult:
    passed: bool = True
    hook_name: str = ""
    output: Any = None


@dataclass
class CascadeResult:
    passed: bool = True
    reason: str = ""
    gates_checked: int = 0
    details: list[GateCheckResult] = field(default_factory=list)


# ============================================================
# Search / Evolution / Dream / Status
# ============================================================

@dataclass
class SearchHit:
    node_id: str = ""
    score: float = 0.0
    content: str = ""
    snippet: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResults:
    hits: list[SearchHit] = field(default_factory=list)
    total_count: int = 0
    query: str = ""
    duration_ms: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class DreamResult:
    patterns_found: int = 0
    beliefs_synthesized: int = 0
    connections_discovered: int = 0
    insights: list[str] = field(default_factory=list)


@dataclass
class EvolutionOutcome:
    result: EvolutionResult = EvolutionResult.NOOP
    fitness_before: float = 0.0
    fitness_after: float = 0.0
    duration_ms: float = 0.0
    details: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemStatus:
    node_count: int = 0
    edge_count: int = 0
    active_sessions: int = 0
    uptime_seconds: float = 0.0
    health: str = "unknown"
    version: str = "1.0.0"
    mechanisms: int = 99
    details: dict[str, Any] = field(default_factory=dict)


# ============================================================
# Configuration
# ============================================================

@dataclass
class ZConfig:
    database_path: str = "prometheus_nexus.db"
    max_nodes: int = 100_000
    max_edges: int = 1_000_000
    fts_tokenizer: str = "porter"
    branch_main: str = "main"
    security_posture: SecurityPosture = SecurityPosture.HARDENED
    autonomy_level: AutonomyLevel = AutonomyLevel.L2_SUPERVISED
    trust_level: TrustLevel = TrustLevel.VERIFIED
