"""Prometheus Ultra — 127-mechanism self-evolving AI agent reinforcement system.

Unified from Genesis(99 mechanisms), Omega-Omega(90 mechanisms, branch system),
and Z:\Prometheus Ω(47 mechanisms, deep evolution + 4-layer defense).
"""

from prometheus_nexus.life import Omega
from prometheus_nexus.foundation.schema import (
    MemoryLayer, NodeType, EdgeType, TrustLevel, AutonomyLevel,
    SecurityPosture, EvolutionDirection, LifecycleAction, GateResult,
    CommitState, ProvenanceType, ConstraintKind, WriteOperator,
    Strictness, RiskLevel, GraderType, EvolutionResult, MemoryScope,
    MemoryTier, FailureMode, AlertLevel,
    generate_uuidv7,
    WeibullParams, NodeFeedback, FailureLog, Node, Edge,
    Constraint, Provenance,
    GateCheckResult, WriteGateResult, LifecycleDecision,
    EvolutionCheckResult, VerificationResult, HookResult,
    SearchHit, SearchResults, DreamResult, EvolutionOutcome,
    SystemStatus, ZConfig,
)
from prometheus_nexus.foundation.store import MinervaStore, IronLawViolation

__version__ = "1.0.0"

__all__ = [
    "Omega",
    "MinervaStore", "IronLawViolation",
    "NodeType", "EdgeType", "MemoryTier", "MemoryLayer",
    "GateResult", "EvolutionResult", "EvolutionOutcome",
    "Node", "Edge", "ZConfig", "generate_uuidv7",
    "SearchHit", "SearchResults", "DreamResult", "SystemStatus",
    "TrustLevel", "AutonomyLevel", "SecurityPosture", "AlertLevel",
    "EvolutionDirection", "LifecycleAction", "CommitState",
    "ProvenanceType", "ConstraintKind", "WriteOperator",
    "Strictness", "RiskLevel", "GraderType", "MemoryScope",
    "FailureMode", "WeibullParams", "NodeFeedback", "FailureLog",
    "Constraint", "Provenance", "GateCheckResult", "WriteGateResult",
    "LifecycleDecision", "EvolutionCheckResult", "VerificationResult",
    "HookResult",
]
