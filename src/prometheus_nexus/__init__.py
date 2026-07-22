"""Prometheus Ultra — 127-mechanism self-evolving AI agent reinforcement system.

Unified from Genesis(99 mechanisms), Omega-Omega(90 mechanisms, branch system),
and Z:\\Prometheus Ω(47 mechanisms, deep evolution + 4-layer defense).

架构优化 P1 (2026-07-23): 延迟导入 Omega。
原 __init__ 顶层 `from prometheus_nexus.life import Omega` 会触发 life →
services.server → uvicorn 全链, 导致 import 任何子模块(prometheus_nexus.X)
都拉起 5333 行主循环 + 网络栈, 严重拖慢测试/工具/CI。

改为 PEP 562 模块级 __getattr__: 仅当显式访问 `prometheus_nexus.Omega` 时才
import life。foundation.schema / store 保留顶层导出(它们是轻量纯数据/存储层,
且被高频使用; 经实测不触发 life 链)。
"""

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
    SearchHit, SearchResults, DreamResult, EvolutionOutcome, SystemStatus,
    ZConfig,
)
from prometheus_nexus.foundation.store import MinervaStore, IronLawViolation

__version__ = "1.0.0"

# PEP 562 延迟导入: Omega 仅在被显式访问时才加载 life 链
def __getattr__(name: str):
    if name == "Omega":
        from prometheus_nexus.life import Omega as _Omega

        return _Omega
    raise AttributeError(f"module 'prometheus_nexus' has no attribute {name!r}")


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
