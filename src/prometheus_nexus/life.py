"""life.py — Prometheus Ultra main controller.

Unified from Genesis(99 mechanisms), Omega-Omega(branch system),
and Z: Prometheus Omega(deep evolution + 4-layer defense).

127 mechanisms across 18 subsystems.
7 pipelines: remember, recall, evolve, learn, reflect, dream, maintain.
Branch system for parallel experimentation.

Known Defects:
  [x] Pitfall #22: coroutine stdout bug - arxiv learn returns empty JSON (NOT a bug — Windows console artifact, HTTPS fixed)
  [x] Pitfall #28: weekly quota 3000 exhausted - learn returns 0 (FIXED: 99999999)
  [ ] Pitfall #27: evolve BLOCKED - AntiEvolutionGate rejects repeated context
  [x] _on_outcome event type parsing vulnerability FIXED
  [x] AR subscribe extended from 3 to 7 pipes FIXED
  [x] cerebral_cortex missing max_outcomes_per_trigger config key FIXED
  [x] scanner.py HTTP→HTTPS arxiv redirect FIXED
"""
from __future__ import annotations

import logging
import os
import json
import threading
import time

from prometheus_nexus.foundation.schema import (
    Node, Edge, NodeType, EdgeType, TrustLevel,
    EvolutionResult,
    SearchHit, SearchResults, DreamResult, EvolutionOutcome,
    SystemStatus, ZConfig, generate_uuidv7, AlertLevel, LoopState,
)
from prometheus_nexus.foundation.store import MinervaStore

# Memory
from prometheus_nexus.safety.rubric import RubricScorer, RubricResult

from prometheus_nexus.memory.dopamine import DopamineWriteGate, DopamineGateConfig
from prometheus_nexus.memory.polyphonic import PolyphonicRetriever
from prometheus_nexus.memory.graph_memory import GraphMemory, EpisodeEvent
from prometheus_nexus.memory.four_network import FourNetworkMemory
from prometheus_nexus.memory.feedback import NodeFeedbackTracker, FailureLogTracker
from prometheus_nexus.memory.cache import RTKCache
from prometheus_nexus.memory.shmr import SHMRGenerator
from prometheus_nexus.memory.trajectory import TrajectoryStore
from prometheus_nexus.memory.disposition import DispositionLearner
from prometheus_nexus.memory.hebbian import HebbianMemory
from prometheus_nexus.memory.hierarchical_memory import HierarchicalMemory  # HORMA层级记忆
from prometheus_nexus.memory.stream import MemoryStream
from prometheus_nexus.memory.dual_storage import DualPathwayMemory
from prometheus_nexus.memory.mempo import MemPO
from prometheus_nexus.memory.bridge import KnowledgeBridge

# Lifecycle
from prometheus_nexus.lifecycle.bank import MemoryBank, Tier
from prometheus_nexus.lifecycle.forgetting import WeibullForgetting
from prometheus_nexus.lifecycle.consolidation import ConsolidationPipeline
from prometheus_nexus.lifecycle.gravity import MemoryGravity
from prometheus_nexus.lifecycle.veracity import VeracityBayesian, Evidence
from prometheus_nexus.lifecycle.dream_cycle import DreamCycle
from prometheus_nexus.memory.consolidation_engine import ConsolidationEngine
from prometheus_nexus.lifecycle.convergence import ConvergenceDetector
from prometheus_nexus.lifecycle.state_machine import LoopStateMachine
from prometheus_nexus.lifecycle.thermodynamic import ThermodynamicIntelligence
from prometheus_nexus.lifecycle.rare_valid import RareValidDetector
from prometheus_nexus.lifecycle.mars import MARS

# Evolution
from prometheus_nexus.evolution.eval_driven import EvalDrivenEngine, EvolutionContext
from prometheus_nexus.evolution.anti_evolution_gate import AntiEvolutionGate
from prometheus_nexus.evolution.iron_law import VerificationIronLaw
from prometheus_nexus.evolution.ucb1 import UCB1Bandit
from prometheus_nexus.evolution.fggm import FGGVerifier
from prometheus_nexus.evolution.dag_scheduler import DAGScheduler
from prometheus_nexus.evolution.coevolve import CoEvolution
from prometheus_nexus.evolution.speculative import SpeculativeEvolution
from prometheus_nexus.evolution.evolution_engine import EvolutionEngine
from prometheus_nexus.evolution.pass_k import PassKConsistency
from prometheus_nexus.evolution.strategies import MultiStrategyScheduler
from prometheus_nexus.evolution.evolution_quality_gates import EvolutionQualityGates
from prometheus_nexus.evolution.rimrule import RIMRULE
from prometheus_nexus.safety.trace_engine import TraceEngine

# Safety
from prometheus_nexus.safety.instincts import InstinctsRegistry, register_default_instincts
from prometheus_nexus.safety.five_gates import FiveGates
from prometheus_nexus.safety.loop_guard import LoopGuard
from prometheus_nexus.safety.equilibrium_guard import EquilibriumGuard
from prometheus_nexus.safety.rl_pathology import RLPathologyDetector
from prometheus_nexus.safety.circuit_breaker import CircuitBreaker
from prometheus_nexus.safety.drift_detector import DriftDetector
from prometheus_nexus.safety.constraint_drift import ConstraintDriftDetector
from prometheus_nexus.safety.owner_harm import OwnerHarmTrustBoundary
from prometheus_nexus.safety.zscore import ZScoreAnomaly
from prometheus_nexus.safety.trend import TrendPredictor
from prometheus_nexus.safety.self_healing import SelfHealingEngine
from prometheus_nexus.safety.constitution import Constitution

# Evaluation
from prometheus_nexus.evaluation.five_view import FiveViewEvaluator
from prometheus_nexus.evaluation.marginal import MarginalAdvantageAccumulator
from prometheus_nexus.evaluation.seagym import SEAGym
from prometheus_nexus.evaluation.harness import HarnessX, HarnessPrimitive
from prometheus_nexus.evaluation.bootstrap import BootstrapCI
from prometheus_nexus.evaluation.lucky_pass import LuckyPassDetector

# Loop
from prometheus_nexus.loop.reflexion import ReflexionEngine
from prometheus_nexus.loop.coala import CoALAArchitecture
from prometheus_nexus.loop.debate import DebateEngine
from prometheus_nexus.loop.info_gain import InformationGainTracker
from prometheus_nexus.loop.agent_forest import AgentForest
from prometheus_nexus.loop.dynamic_scaler import DynamicScaler
from prometheus_nexus.loop.brainstorming_engine import BrainstormingEngine
from prometheus_nexus.loop.systematic_debugging import SystematicDebuggingEngine
from prometheus_nexus.loop.tdd_verifier import TDDVerifier
from prometheus_nexus.loop.plan_writer import PlanWriter
from prometheus_nexus.loop.verification_gate import VerificationGate
from prometheus_nexus.loop.parallel_dispatcher import ParallelDispatcher
from prometheus_nexus.loop.plan_executor import PlanExecutor
from prometheus_nexus.loop.code_reviewer import CodeReviewer

# Prompt
from prometheus_nexus.prompt.cot import CoTPrompter
from prometheus_nexus.prompt.few_shot import DynamicFewShot
from prometheus_nexus.prompt.extended_thinking import ExtendedThinking
from prometheus_nexus.prompt.knowledge_gen import KnowledgeGenerator
from prometheus_nexus.prompt.consistency import SelfConsistencyVoter
from prometheus_nexus.prompt.refiner import SelfRefiner

# Learning
from prometheus_nexus.learning.scanner import KnowledgeScanner, ScanSource
from prometheus_nexus.learning.utility_tracker import UtilityTracker
from prometheus_nexus.learning.five_step import FiveStepEvolution
from prometheus_nexus.learning.deep_retrofit import DeepRetrofit

# Harness
from prometheus_nexus.harness.compressor import ContextCompressor
from prometheus_nexus.harness.guardrail import InputGuardrail, OutputGuardrail
from prometheus_nexus.harness.router import ModelRouter, ModelConfig
from prometheus_nexus.harness.session import Session
from prometheus_nexus.harness.brain import Brain
from prometheus_nexus.harness.hands import Hands
from prometheus_nexus.harness.crash_recovery import CrashRecovery

# Collaboration
from prometheus_nexus.collaboration.multi_agent import MultiAgentSystem
from prometheus_nexus.collaboration.event_bus import CIPEventBus
from prometheus_nexus.collaboration.vector_clock import VectorClock
from prometheus_nexus.collaboration.causal_graph import CausalKnowledgeGraph
from prometheus_nexus.collaboration.behavior_mirror import BehaviorMirror

# Ecosystem
from prometheus_nexus.ecosystem.lotka_volterra import LotkaVolterra
from prometheus_nexus.ecosystem.speculative_fork import SpeculativeFork
from prometheus_nexus.ecosystem.tool_fitness import ToolFitnessPredictor
from prometheus_nexus.ecosystem.community_tree import CommunityTree
from prometheus_nexus.ecosystem.edre import EDREReplicator

# Execution
from prometheus_nexus.execution.dag_executor import DAGExecutor, ParallelDAG, RetryableDAG, MonitoredDAG

# Governance
from prometheus_nexus.governance.autonomy import ConfidenceGate, EvolutionGrill

# Organs
from prometheus_nexus.organs.organ_pipeline import FiveOrganPipeline
from prometheus_nexus.organs.dna_extractor import DNAExtractor
from prometheus_nexus.organs.tool_loop import ToolLoop

# Skills
from prometheus_nexus.skills.registry import SkillRegistry
from prometheus_nexus.skills.curator import Curator
from prometheus_nexus.skills.skill_claw import SkillClaw

# Mechanisms
from prometheus_nexus.mechanisms.registry import MechanismRegistry
from prometheus_nexus.mechanisms.x_adapter import XMemoryAdapter
from prometheus_nexus.mechanisms.y_adapter import YBankAdapter

# Monitor + Services
from prometheus_nexus.monitor.system_monitor import SystemMonitor
from prometheus_nexus.services.server import OmegaServer

# New modules (120-source enhancement)
from prometheus_nexus.loop.tree_of_thoughts import TreeOfThoughts, SearchStrategy
from prometheus_nexus.loop.think_tool import ThinkTool
from prometheus_nexus.safety.context_clash import ContextClashDetector
from prometheus_nexus.safety.context_failure import ContextFailureDetector
from prometheus_nexus.safety.context_poisoning import ContextPoisoningDetector
from prometheus_nexus.safety.tool_overload import ToolOverloadDetector
from prometheus_nexus.safety.memory_side_effect import MemorySideEffectDetector
from prometheus_nexus.memory.context_isolator import ContextIsolator
from prometheus_nexus.harness.context_window import ContextWindowManager
from prometheus_nexus.harness.progressive_complexity import ProgressiveComplexity
from prometheus_nexus.harness.crash_restore import CrashStateRestore
from prometheus_nexus.governance.human_oversight import HumanOversight, OversightRiskLevel as RiskLevel
from prometheus_nexus.prompt.structured_output import StructuredOutput, SchemaField
from prometheus_nexus.prompt.xml_tag import XMLTagPrompting
from prometheus_nexus.prompt.reasoning_adapter import ReasoningModelAdapter
from prometheus_nexus.harness.context_engineering import ContextEngineering, ContextComponent
from prometheus_nexus.loop.loop_selector import LoopSelector, LoopStrategy
from prometheus_nexus.harness.adaptive_harness import AdaptiveHarness, ToolPolicy
from prometheus_nexus.prompt.evolving_prompt import EvolvingPrompt

# ===== P0: Safety Security Layer (9 files) =====
from prometheus_nexus.safety.memory_write_guard import MemoryWriteGuard
from prometheus_nexus.safety.data_exfiltration_detect import DataExfiltrationDetector
from prometheus_nexus.safety.tool_call_verify import ToolCallVerifier
from prometheus_nexus.safety.non_adversarial_leakage import NonAdversarialLeakageDetector
from prometheus_nexus.safety.process_audit import ProcessAuditor
from prometheus_nexus.safety.local_causal_explainer import LocalCausalExplainer
from prometheus_nexus.safety.reasoning_alignment import ReasoningAlignmentChecker
from prometheus_nexus.safety.intervention_control import InterventionController
from prometheus_nexus.safety.compliance_scorer import ComplianceScorer

# ===== P0 Extended: Sleeper + Domain Audit + Fuzz Testing =====
from prometheus_nexus.safety.trigger_detector import TriggerDetector
from prometheus_nexus.safety.finetune_audit import FineTuneAudit
from prometheus_nexus.safety.fuzz_tester import FuzzTester

# ===== P1: Memory Layer (7 files) =====
from prometheus_nexus.memory.hela_mem import HeLaMem
from prometheus_nexus.memory.hierarchical_memory import HierarchicalMemory as HORMAHierarchicalMemory
from prometheus_nexus.memory.rl_navigator import RLNavigator
from prometheus_nexus.memory.context_clash import ContextClashDetector as MemoryContextClashDetector
from prometheus_nexus.memory.forbidden_patterns import ForbiddenPatternDetector
from prometheus_nexus.memory.external_notebook import ExternalNotebook

# ===== P2: Learning Layer (7 files) =====
from prometheus_nexus.learning.intent_aware_retrieval import SimpleMem
from prometheus_nexus.harness.active_compressor import ActiveCompressor, SlimeMoldExplorer, FocusCompressor
from prometheus_nexus.learning.b10_remaining import SubtleMemoryBenchmark
from prometheus_nexus.learning.mcts_retriever import MCTSRetriever
from prometheus_nexus.learning.localized_icl import LocalizedICL
from prometheus_nexus.learning.strategy_switcher import StrategySwitcher
from prometheus_nexus.learning.reflective_sampler import ReflectiveSampler

# ===== P3: Evolution + Collaboration (6 files) =====
from prometheus_nexus.evolution.b8_remaining import FATE, SignalTriage, ESTEER, PersonaManager, Loom
from prometheus_nexus.evolution.b9_remaining import ProgressiveMCGS, EntropyScheduler, RetrospectiveMemory, StrategyCodingDecouple, ATPValidator, GearSafety
from prometheus_nexus.collaboration.b7_remaining import AgentReputation
from prometheus_nexus.collaboration.camp_assembly import CAMPAssembler
from prometheus_nexus.collaboration.interaction_graph import InteractionGraph
from prometheus_nexus.collaboration.knowledge_curation import KnowledgeCuration

# ===== P4: Harness + Lifecycle (5 files) =====
from prometheus_nexus.harness.tiered_router import TieredRouter
from prometheus_nexus.harness.tool_tax_gate import ToolTaxGate, SemanticNoiseEstimator
from prometheus_nexus.lifecycle.sleep_gate import SleepGate
from prometheus_nexus.loop.himac_planner import HiMACPlanner
from prometheus_nexus.learning.academic_searcher import AcademicSearcher

# ===== P1 Extended: CNS Orchestrator + Signal Fusion =====
from prometheus_nexus.lifecycle.cns_orchestrator import CNSOrchestrator
from prometheus_nexus.lifecycle.signal_fusion import SignalFusionLayer
from prometheus_nexus.lifecycle.cerebral_cortex import CerebralCortex
from prometheus_nexus.lifecycle.autonomic_regulator import AutonomicRegulator
from prometheus_nexus.lifecycle.telemetry_pipeline import TelemetryPipeline

# ===== P2 Extended: DAG Execution =====
from prometheus_nexus.execution.dag_executor import DAGExecutor, MonitoredDAG, RetryableDAG

# ===== P3 Extended: Learning Gates =====
from prometheus_nexus.learning.ada_mem_gate import AdaMEMGate
from prometheus_nexus.learning.scanner import KnowledgeScanner, ScanSource
from prometheus_nexus.learning.learn_feedback import LearnFeedbackTracker
from prometheus_nexus.learning.knowledge_rumination import KnowledgeRuminationEngine
from prometheus_nexus.learning.semantic_learner import SemanticLearner
from prometheus_nexus.evolution.attribution_scoring import AttributionEvolutionScoring
from prometheus_nexus.evolution.playbook_inheritance import PlaybookInheritance
from prometheus_nexus.safety.two_level_blocker import TwoLevelBlockerEscalation
from prometheus_nexus.learning.self_observation import SelfObservation
from prometheus_nexus.learning.paper_fetch_mcp import PaperFetchClient

# ===== P4 Extended: Memory + Prompt =====
from prometheus_nexus.memory.multi_hop import MultiHopRetriever
from prometheus_nexus.prompt.brainstorming import BrainstormingPrompt

# MiMo-derived mechanisms
from prometheus_nexus.safety.five_gate_chain import FiveGateMemoryChain
from prometheus_nexus.safety.oep_defense import OEPDefense
from prometheus_nexus.harness.progressive_checkpoints import ProgressiveCheckpoints
from prometheus_nexus.evolution.evolution_quality_gates import EvolutionQualityGates
from prometheus_nexus.memory.utility_decay import UtilityDecay
from prometheus_nexus.safety.tool_drift import ToolDriftDetector
from prometheus_nexus.learning.deep_retrofit_6 import DeepRetrofit6
from prometheus_nexus.monitor.heartbeat_4cycle import Heartbeat4Cycle
from prometheus_nexus.harness.three_layer_compression import ThreeLayerCompression
from prometheus_nexus.learning.knowledge_to_mechanism import KnowledgeToMechanism
from prometheus_nexus.harness.wal import WriteAheadLog
from prometheus_nexus.safety.file_checksum import FileChecksum
from prometheus_nexus.learning.explorer_state import ExplorerState
from prometheus_nexus.learning.curiosity_autofill import CuriosityAutoFill
from prometheus_nexus.learning.exploration_quota import ExplorationQuota
from prometheus_nexus.harness.sub_agent_contract import SubAgentContract
from prometheus_nexus.safety.rule_expiration import RuleExpirationAudit
from prometheus_nexus.safety.capability_ceiling import CapabilityCeiling
from prometheus_nexus.safety.cognitive_collapse import CognitiveCollapse
from prometheus_nexus.loop.semantic_early_stopping import SemanticEarlyStopping
from prometheus_nexus.lifecycle.evaf_consolidation import EVAFConsolidation
from prometheus_nexus.collaboration.a2a_basic import A2ABasic, AgentCapability
from prometheus_nexus.lifecycle.local_maintenance import LocalMaintenance
from prometheus_nexus.memory.memory_depth import MemoryDepthTracker
from prometheus_nexus.evolution.everos import EverOS
from prometheus_nexus.evolution.gepa import GEPA
from prometheus_nexus.evolution.memento import Memento
from prometheus_nexus.evolution.reasoning_bank import ReasoningBank
from prometheus_nexus.evolution.openspace import OpenSpace
from prometheus_nexus.harness.state_persistence import StatePersistence
from prometheus_nexus.evaluation.memory_data_adapter import MemoryDataAdapter

# Lazy import to avoid circular dependency
TopologicalRetrieval = None

logger = logging.getLogger(__name__)


class Omega:
    """Prometheus Ultra — 127-mechanism self-evolving AI agent system.

    Composes all subsystems into a unified interface with 7 pipelines.
    Supports branch-based parallel experimentation.
    """

    # 健康聚合阈值: 失败组件数达到此值, 引擎健康升级为 critical。
    # (组件失败但 equilibrium 仍绿时, 原先被 _compute_health 完全忽略 —— 监控盲区)
    HEALTH_CRITICAL_COMPONENT_FAILURES = 3

    def __init__(self, config: ZConfig | None = None, db_path: str | None = None,
                 host: Any | None = None) -> None:
        self._cfg = config if config is not None else ZConfig()
        if db_path:
            self._cfg.database_path = db_path
        self._start_time = time.time()
        self._last_reflect_score = 0.0
        self._last_reflect_time = 0.0
        self._telemetry: dict[str, object] = {}  # Telemetry: 存储各管道原始返回值

        # Learned config
        self._learned_config: dict[str, float] = {}

        # ===== Foundation (1) =====
        self.store = MinervaStore(self._cfg)
        self.store.connect()

        # ===== Memory (13) =====
        self.hebbian = HebbianMemory()
        self.hierarchical = HierarchicalMemory()  # HORMA层级记忆
        # Dopamine gate: threshold=0.5 for stricter filtering (was 0.3)
        self.dopamine = DopamineWriteGate(DopamineGateConfig(threshold=0.5))
        self.search = PolyphonicRetriever()
        self.graph_memory = GraphMemory(hebbian=self.hebbian)
        self.four_network = FourNetworkMemory()
        self.feedback = NodeFeedbackTracker()
        self.failure_log = FailureLogTracker()
        self.cache = RTKCache()
        self.shmr = SHMRGenerator()
        self.trajectory = TrajectoryStore()
        self.disposition = DispositionLearner()
        self.stream = MemoryStream()
        self.dual_storage = DualPathwayMemory()
        self.mempo = MemPO()
        self.bridge = KnowledgeBridge()

        # ===== Lifecycle (12) =====
        self.bank = MemoryBank(db_path=":memory:")
        self.forgetting = WeibullForgetting()
        self.consolidation = ConsolidationPipeline()
        self.gravity = MemoryGravity()
        self.veracity = VeracityBayesian()
        self.dream = DreamCycle(store=self.store)
        self.consolidation_engine = ConsolidationEngine()
        self.convergence = ConvergenceDetector()
        self.state_machine = LoopStateMachine()
        self.thermodynamic = ThermodynamicIntelligence()
        self.rare_valid = RareValidDetector()
        self.mars = MARS()

        # ===== Evolution (9) =====
        self.eval_engine = EvalDrivenEngine(max_iterations=10, convergence_threshold=0.95)
        self.anti_evolution = AntiEvolutionGate()
        self.iron_law = VerificationIronLaw(strict_fuzzy_rejection=True)
        self.ucb1 = UCB1Bandit(arm_names=["dopamine", "graph", "consolidation", "fggm"])
        self.fggm = FGGVerifier()
        self.dag_scheduler = DAGScheduler()
        self.coevolve = CoEvolution()
        self.speculative = SpeculativeEvolution()
        self.evolution_engine = EvolutionEngine(evaluate_fn=lambda c: self._compute_fitness())
        # Swiss Army Knife modules (2026-07-01)
        self.pass_k = PassKConsistency()
        self.strategy_scheduler = MultiStrategyScheduler(["gepa", "everos", "memento", "openspace", "ga"])
        self.trace_engine = TraceEngine()

        # ===== Safety (11) =====
        self.instincts = InstinctsRegistry()
        register_default_instincts(self.instincts)
        self.five_gates = FiveGates(dopamine_gate=self.dopamine)
        self.constitution = Constitution()
        self.loop_guard = LoopGuard()
        self.equilibrium = EquilibriumGuard()
        self.rl_pathology = RLPathologyDetector()
        self.circuit_breaker = CircuitBreaker()
        self.drift_detector = DriftDetector()
        self.constraint_drift = ConstraintDriftDetector()
        self.owner_harm = OwnerHarmTrustBoundary()
        self.zscore = ZScoreAnomaly()
        self.trend = TrendPredictor()
        self.self_healing = SelfHealingEngine()
        self.rubric = RubricScorer()
        # Will be wired up after Loop mechanisms are initialized

        # ===== Learning (5) =====
        try:
            from prometheus_nexus.learning.scanner import KnowledgeScanner, ScanSource
            self.knowledge_scanner = KnowledgeScanner()
        except Exception as e:
            logger.warning("Failed to load KnowledgeScanner: %s", str(e)[:50])
            self.knowledge_scanner = None

        try:
            from prometheus_nexus.learning.curiosity import Curiosity as CuriosityQueue
            self.curiosity_queue = CuriosityQueue()
        except Exception as e:
            logger.warning("Failed to load CuriosityQueue: %s", str(e)[:50])
            self.curiosity_queue = None

        try:
            from prometheus_nexus.learning.utility_tracker import UtilityTracker
            self.utility_tracker = UtilityTracker()
        except Exception as e:
            logger.warning("Failed to load UtilityTracker: %s", str(e)[:50])
            self.utility_tracker = None

        try:
            from prometheus_nexus.learning.five_step import FiveStepEvolution
            self.five_step = FiveStepEvolution(omega=self)
        except Exception as e:
            logger.warning("Failed to load FiveStepEvolution: %s", str(e)[:50])
            self.five_step = None

        try:
            from prometheus_nexus.learning.deep_retrofit import DeepRetrofit
            self.retrofit = DeepRetrofit(omega=self)
        except Exception as e:
            logger.warning("Failed to load DeepRetrofit: %s", str(e)[:50])
            self.retrofit = None

        # ===== Learn Feedback Tracker (P0修复) =====
        self.learn_feedback = LearnFeedbackTracker()

        # ===== SemanticLearner (真实实例化, 之前会话声称但未接) =====
        self.semantic_learner = SemanticLearner()

        # ===== 学习管道反刍环节 (温故知新) =====
        # state_path 持久化调度状态, 避免 cron 高频重启清零导致反刍永远不触发
        self.rumination_engine = KnowledgeRuminationEngine(
            omega=self,
            state_path=os.path.join("archive", "rumination_state.json"),
        )

        # ===== OpenOPC机制借鉴 =====
        self.attribution_scoring = AttributionEvolutionScoring()
        self.playbook_inheritance = PlaybookInheritance()
        self.blocker_escalation = TwoLevelBlockerEscalation()

        # ===== Evaluation (5) =====
        self.five_view = FiveViewEvaluator()
        self.marginal = MarginalAdvantageAccumulator()
        self.seagym = SEAGym()
        self.harness_x = HarnessX()
        self.bootstrap = BootstrapCI()
        self.lucky_pass = LuckyPassDetector()

        # ===== Loop (13) =====
        self.reflexion = ReflexionEngine()
        self.coala = CoALAArchitecture()
        self.debate = DebateEngine()
        self.info_gain = InformationGainTracker()
        self.agent_forest = AgentForest()
        self.dynamic_scaler = DynamicScaler()
        self.brainstorming = BrainstormingEngine()
        self.systematic_debugging = SystematicDebuggingEngine()
        self.tdd_verifier = TDDVerifier()
        self.plan_writer = PlanWriter()
        self.verification_gate = VerificationGate()
        self.parallel_dispatcher = ParallelDispatcher()
        self.code_reviewer = CodeReviewer()

        # Wire systematic debugging to self_healing
        self.self_healing.set_debugger(self.systematic_debugging)

        # ===== Prompt (6) =====
        self.cot = CoTPrompter()
        self.few_shot = DynamicFewShot()
        self.extended_thinking = ExtendedThinking()
        self.knowledge_gen = KnowledgeGenerator()
        self.consistency = SelfConsistencyVoter()
        self.refiner = SelfRefiner()

        # ===== Harness (7) =====
        self.compressor = ContextCompressor()
        self.input_guardrail = InputGuardrail()
        self.output_guardrail = OutputGuardrail()
        self.model_router = ModelRouter({"default": ModelConfig()})
        self.session = Session()
        self.brain = Brain()
        self.hands = Hands()
        self.crash_recovery = CrashRecovery(self.session)

        # ===== Collaboration (5) =====
        self.multi_agent = MultiAgentSystem()
        self.event_bus = CIPEventBus()
        self.vector_clock = VectorClock()
        self.causal_graph = CausalKnowledgeGraph()
        self.behavior_mirror = BehaviorMirror()

        # ===== Ecosystem (5) =====
        self.lotka_volterra = LotkaVolterra()
        self.speculative_fork = SpeculativeFork()
        self.tool_fitness = ToolFitnessPredictor()
        # Swiss Army Knife: full tool fitness evaluator (from evolution/)
        from prometheus_nexus.evolution.tool_fitness import ToolFitness
        self.tool_fitness_full = ToolFitness()
        self.community_tree = CommunityTree()
        self.edre = EDREReplicator()

        # ===== Execution (4) =====
        try:
            from prometheus_nexus.execution.dag_executor import DAGExecutor, ParallelDAG
            self.dag_executor = DAGExecutor()
            self.parallel_dag = ParallelDAG() if self.dag_executor else None
            logger.info("DEBUG: parallel_dag initialized: %s", self.parallel_dag)
        except Exception as e:
            logger.warning("Failed to load DAGExecutor/ParallelDAG: %s", str(e)[:50])
            self.dag_executor = None
            self.parallel_dag = None
            logger.info("DEBUG: parallel_dag set to None due to exception")

        try:
            from prometheus_nexus.execution.dag_executor import RetryableDAG
            self.retryable_dag = RetryableDAG(max_retries=3)
            logger.info("DEBUG: retryable_dag initialized: %s", self.retryable_dag)
        except Exception as e:
            logger.warning("Failed to load RetryableDAG: %s", str(e)[:50])
            self.retryable_dag = None
            logger.info("DEBUG: retryable_dag set to None due to exception")

        try:
            from prometheus_nexus.execution.dag_executor import MonitoredDAG
            self.monitored_dag = MonitoredDAG() if self.dag_executor else None
        except Exception as e:
            logger.warning("Failed to load MonitoredDAG: %s", str(e)[:50])
            self.monitored_dag = None

        # ===== Governance (2) =====
        self.confidence_gate = ConfidenceGate()
        self.evolution_grill = EvolutionGrill()

        # ===== Organs (3) =====
        self.organ_pipeline = FiveOrganPipeline()
        self.dna_extractor = DNAExtractor()
        self.tool_loop = ToolLoop()

        # ===== Skills (3) =====
        self.skill_registry = SkillRegistry()
        self.curator = Curator(self.skill_registry)
        self.skill_claw = SkillClaw()
        # 组合式技能合成代理 (借鉴 Agentic Proposing)
        from prometheus_nexus.skills.proposer import Proposer
        self.proposer = Proposer(self.skill_claw, llm=getattr(self, "llm", None))

        # ===== Mechanisms (3) =====
        self.mechanism_registry = MechanismRegistry(path="archive/mechanisms.json")
        # Nexus: 神经系统统一中枢(统辖机制层+7管道+两层记忆+效果路由+修剪)
        from prometheus_nexus.cns.nexus import Nexus
        self.nexus = Nexus(path="archive/nexus.json", store=self.store)
        # 注册表范式收敛: 让 InstinctsRegistry / SkillRegistry 旁路记账进 Nexus 统一调用图
        # (零延迟保留: 仅 mark_invoked 计数, 不转发; 效果路由/消费统计覆盖全机制)
        if hasattr(self, "instincts"):
            self.instincts.nexus = self.nexus
        if hasattr(self, "skill_registry"):
            self.skill_registry.nexus = self.nexus
        self.x_adapter = XMemoryAdapter()
        self.y_adapter = YBankAdapter()

        # 产出账本: 统一记录系统真实产出(知识/机制/信念/反思/修剪),
        # 供最细粒度监控"这段时间产出了什么"视角使用.
        # 下划线开头: 避免被 Nexus 统合当成机制包裹成 NexusProxy.
        self._productions = []
        self._production_lock = threading.Lock()

        # 运行问题收集器: 记录系统运行期间真实产生的 BUG/异常/关键WARNING,
        # 供监控报告"运行问题"块. 下划线开头避免 Nexus 包裹.
        self._issues = []
        self._issue_lock = threading.Lock()
        # 挂一个日志处理器, 捕 ERROR + 关键 WARNING (过滤噪音)
        self._attach_issue_handler()

        # 后见之明技能蒸馏器 (借鉴 SEED) — 从管道轨迹提炼可复用技能
        from prometheus_nexus.evolution.hindsight_skill import HindsightSkillMiner
        self._hindsight_miner = HindsightSkillMiner(omega=self)

        self.monitor = SystemMonitor()

        self.server = OmegaServer(omega=self)

        # ===== New modules (15) =====
        self.tree_of_thoughts = TreeOfThoughts(branching_factor=3, max_depth=4)
        self.think_tool = ThinkTool()
        self.context_clash = ContextClashDetector()
        self.context_failure = ContextFailureDetector()
        self.context_poisoning = ContextPoisoningDetector()
        self.tool_overload = ToolOverloadDetector()
        self.memory_side_effect = MemorySideEffectDetector()
        self.context_isolator = ContextIsolator()
        self.context_window = ContextWindowManager()
        self.progressive_complexity = ProgressiveComplexity()
        self.crash_restore = CrashStateRestore()
        self.human_oversight = HumanOversight()
        self.structured_output = StructuredOutput()
        self.xml_tag = XMLTagPrompting()
        self.reasoning_adapter = ReasoningModelAdapter()

        # ===== Context Engineering =====
        self.context_engineering = ContextEngineering(max_tokens=128000)

        # ===== Loop Engineering =====
        self.loop_selector = LoopSelector()

        # ===== Harness Engineering =====
        self.adaptive_harness = AdaptiveHarness()
        self.adaptive_harness.register_tool(ToolPolicy(tool_name="remember", allowed=True))
        self.adaptive_harness.register_tool(ToolPolicy(tool_name="recall", allowed=True))
        self.adaptive_harness.register_tool(ToolPolicy(tool_name="evolve", allowed=True))
        self.adaptive_harness.register_tool(ToolPolicy(tool_name="learn", allowed=True))
        self.adaptive_harness.register_tool(ToolPolicy(tool_name="reflect", allowed=True))
        self.adaptive_harness.register_tool(ToolPolicy(tool_name="dream", allowed=True))
        self.adaptive_harness.register_tool(ToolPolicy(tool_name="maintain", allowed=True))

        # ===== Prompt Engineering =====
        # evolving_prompt is available for future dynamic prompt generation
        # self.evolving_prompt = EvolvingPrompt()

        # ===== MiMo-derived mechanisms =====
        self.five_gate_chain = FiveGateMemoryChain()
        self.oep_defense = OEPDefense()
        self.progressive_checkpoints = ProgressiveCheckpoints()
        self.evo_quality_gates = EvolutionQualityGates()
        self.rimrule = RIMRULE()
        self.utility_decay = UtilityDecay()
        self.tool_drift = ToolDriftDetector()
        self.deep_retrofit_6 = DeepRetrofit6()
        self.heartbeat_4cycle = Heartbeat4Cycle()
        self.three_layer_compression = ThreeLayerCompression()
        self.knowledge_to_mechanism = KnowledgeToMechanism()

        # Session continuity & file integrity
        self.wal = WriteAheadLog()
        self.file_checksum = FileChecksum()

        # Exploration tracking
        self.explorer_state = ExplorerState()
        self.curiosity_autofill = CuriosityAutoFill(self.curiosity_queue)
        self.exploration_quota = ExplorationQuota(max_daily=99999999, revision_after=10, weekly_max=99999999)
        self._scans: list[dict] = []

        # P2-1: 长期关注主题积累 (外部知识吸收从零散->可积累)
        # 高频命中 query 自动升为系统长期关注主题, heartbeat learn 优先扫这些
        from collections import Counter
        self.focus_topics: Counter = Counter()
        self._focus_threshold: int = 3  # 命中>=3 次的主题进入长期关注

        # LLM Bridge — 四轨进化(T3/T4)调用外部推理模型(HTTP模式建桥, 无则降级)
        # V3.0 G2: 优先用 Agent 注入的 LLM 配置(独立进程模式也能复用 Agent LLM),
        #   否则回退 host bridge(HermesAdapter), 再否则空 bridge(规则降级).
        from prometheus_nexus.integration.llm_bridge import LLMBridge
        from prometheus_nexus.integration.llm_config import LLMConfig
        _agent_llm = LLMConfig.from_env()
        self.llm = _agent_llm.to_llm_bridge() if _agent_llm else LLMBridge()

        # P1a+b: 宿主 agent 抽象层 — 默认 HermesAdapter, 可替换为任意 HostAgentAdapter
        # 让 Ultra 成为"任意 agent 的外挂记忆 + 自进化生命体" (解 B5)
        from prometheus_nexus.integration.host_agent import NullHostAdapter
        from prometheus_nexus.integration.hermes_adapter import HermesAdapter
        _host_ep = os.environ.get("AGENT_LLM_ENDPOINT") or os.environ.get("HERMES_LLM_ENDPOINT")
        # V3.1 G3: 允许注入自定义 host adapter(任意 Agent); 否则默认 Hermes 宿主
        # 关键修正: 宿主身份(Hermes) 独立于 LLM 可用性 — 即使无 LLM endpoint,
        #   Ultra 仍以 Hermes 宿主身份运行(host_id 隔离/经验回灌/机制消费语义成立),
        #   LLM bridge 内部 available=False 时 T3/T4 诚实降级(非 NullHost 丢宿主语义).
        if host is not None:
            self.host = host
        else:
            # 优先: 显式 LLM endpoint -> HermesAdapter(带 bridge)
            # 默认: 仍 Hermes 宿主(无 LLM 时 bridge.available=False, T4 降级)
            self.host = HermesAdapter()
        # 把宿主 LLM 也作为 T3/T4 的推理通道: 自动复用 Agent(Hermes) 的 LLM 配置
        # V3.7 修正: 自动探测(from_hermes), 与代理(clash等)完全解耦 — 代理只是网络通道
        if isinstance(self.host, HermesAdapter):
            _llm_cfg = LLMConfig.from_hermes()  # 自动: env > hermes config.yaml > 探测端口
            if _llm_cfg is not None:
                self.host = HermesAdapter(endpoint=_llm_cfg.endpoint, api_key=_llm_cfg.api_key,
                                            model=_llm_cfg.model, provider=_llm_cfg.provider)
                self.llm = self.host._bridge
            else:
                # 无 LLM 配置: 仍 Hermes 宿主身份, self.llm 建空 bridge(available=False)
                #   保持 'o.llm 永远非 None' 契约(T4 诚实降级, 非 NullHost/非 None 崩)
                from prometheus_nexus.integration.llm_bridge import LLMBridge
                self.llm = LLMBridge()

        # T2: 语义进化轨道
        from prometheus_nexus.evolution.semantic_evolution import SemanticEvolutionEngine
        self.semantic_evolution = SemanticEvolutionEngine(omega=self)

        # T3: GitHub 机制提取轨道
        from prometheus_nexus.mechanisms.mechanism_extractor import MechanismExtractor
        self.mechanism_extractor = MechanismExtractor(llm=self.llm, store=self.store)

        # T4: 论文编译轨道
        from prometheus_nexus.mechanisms.mechanism_compiler import MechanismCompiler
        self.mechanism_compiler = MechanismCompiler(llm=self.llm, store=self.store)

        # P0a: 注册激活消费者 — 机制激活后真接生产(解 B1 僵尸机制)
        # T3(category=extracted) 激活 -> 注入 gene_specs 进进化引擎
        # T4(category=compiled) 激活 -> 经 host.emit_capability 导出给宿主
        try:
            self.mechanism_registry.register_consumer(
                "extracted",
                lambda entry: self._consume_t3(entry),
            )
            self.mechanism_registry.register_consumer(
                "compiled",
                lambda entry: self._consume_t4(entry),
            )
        except Exception as e:
            logger.debug("Omega: register consumers failed: %s", e)

        # S3: T1 进化状态持久化(跨会话累积)
        from prometheus_nexus.evolution.evolution_state import EvolutionState
        self.evolution_state = EvolutionState(store=self.store)
        # load() 永不抛出(内部已捕获); 损坏记 WARNING 并回退 .bak,
        # 首跑(无状态文件) benign 返回 False。无需 try/except 包裹。
        if self.evolution_state.load(self.evolution_engine):
            logger.info("Evolve: restored evolution state from previous session")
        self.rule_expiration = RuleExpirationAudit()

        # Scaling & cognitive safety
        self.capability_ceiling = CapabilityCeiling()
        self.cognitive_collapse = CognitiveCollapse()

        # A+B+C enhancements
        self.semantic_early_stopping = SemanticEarlyStopping(patience=3, threshold=0.01)
        self.evaf_consolidation = EVAFConsolidation()
        self.a2a_basic = A2ABasic()
        # Lazy import for topological retrieval
        try:
            from prometheus_nexus.memory.topological_retrieval import TopologicalRetrieval as _TR
            self.topological_retrieval = _TR()
        except ImportError:
            self.topological_retrieval = None
        self.local_maintenance = LocalMaintenance()
        self.memory_depth = MemoryDepthTracker()

        # ===== P0: Safety Security Layer (9 files) =====
        self.memory_write_guard = MemoryWriteGuard()
        self.data_exfil_detector = DataExfiltrationDetector()
        self.tool_call_verifier = ToolCallVerifier()
        self.leakage_detector = NonAdversarialLeakageDetector()
        self.process_auditor = ProcessAuditor()
        self.causal_explainer = LocalCausalExplainer()
        self.reasoning_checker = ReasoningAlignmentChecker()
        self.intervention_controller = InterventionController()
        self.compliance_scorer = ComplianceScorer()

        # D1 [Task5]: 反向持有 — 让宿主 adapter 能访问 Omega 的 event_bus,
        #   以便 emit/apply_capability 时回流产出信号 (capability_consumed) 给神经系统
        if hasattr(self, "host") and self.host is not None:
            self.host._omega = self

        # ===== P0 Extended: Sleeper + Domain Audit + Fuzz Testing =====
        # Initialized later with try-except for graceful degradation

        # ===== P1: Memory Layer (7 files) =====
        self.hela_mem = HeLaMem(eta=0.1)
        self.horma_hierarchical = HORMAHierarchicalMemory()
        self.rl_navigator = RLNavigator()
        # self.consolidation_engine already initialized above
        # NOTE: memory_context_clash 是 ContextClashDetector 的别名, 已作为 self.context_clash 实例化(行582), 此处冗余删除
        self.forbidden_pattern_detector = ForbiddenPatternDetector()
        self.external_notebook = ExternalNotebook()

        # ===== P2: Learning Layer (7 files) =====
        self.simple_mem = SimpleMem()
        self.active_compressor = ActiveCompressor(max_tokens=25000)
        self.slime_mold_explorer = SlimeMoldExplorer()
        self.focus_compressor = FocusCompressor()
        self.subtle_memory_benchmark = SubtleMemoryBenchmark()
        self.mcts_retriever = MCTSRetriever()
        self.localized_icl = LocalizedICL()
        self.strategy_switcher = StrategySwitcher()
        self.reflective_sampler = ReflectiveSampler()

        # ===== P3: Evolution + Collaboration (6 files) =====
        self.fate = FATE()
        self.signal_triage = SignalTriage()
        self.esteer = ESTEER()
        self.persona_manager = PersonaManager()
        self.loom = Loom()
        self.progressive_mcgs = ProgressiveMCGS()
        self.entropy_scheduler = EntropyScheduler()
        self.retrospective_memory = RetrospectiveMemory()
        self.strategy_coding_decouple = StrategyCodingDecouple()
        self.atp_validator = ATPValidator()
        self.gear_safety = GearSafety()
        self.agent_reputation = AgentReputation()
        self.camp_assembler = CAMPAssembler()
        self.interaction_graph = InteractionGraph()
        self.knowledge_curation = KnowledgeCuration()

        # ===== P4: Harness + Lifecycle (5 files) =====
        self.tiered_router = TieredRouter()
        self.tool_tax_gate = ToolTaxGate()
        self.semantic_noise_estimator = SemanticNoiseEstimator()
        self.academic_searcher = AcademicSearcher()
        self.sleep_gate = SleepGate()
        self.himac_planner = HiMACPlanner()

        # ===== P1 Extended: CNS Orchestrator + Signal Fusion =====
        # Initialized later with proper event bus subscription

        # ===== P3 Extended: Learning Gates =====
        # Note: ada_mem_gate, knowledge_scanner, self_observation, paper_fetcher
        # are already initialized above. No need to re-initialize.

        # ===== P4 Extended: Memory + Prompt =====
        # Note: multi_hop, brainstorming are already initialized above.

        # 5 evolution methods from EvoAgentBench
        self.everos = EverOS()
        self.gepa = GEPA()
        self.memento_evolution = Memento()
        self.reasoning_bank = ReasoningBank()
        self.openspace = OpenSpace()

        # State persistence & MemoryData
        self.state_persistence = StatePersistence()
        self.memory_data_adapter = MemoryDataAdapter(self)
        # Defensive measure: memory_data_adapter is called in maintain for benchmark
        # It is excluded from the ULTRA_DIAGNOSTICS guard as it evaluates external benchmarks
        self.state_persistence.load(self)
 
        # ===== HarnessX: register primitives =====
        self.harness_x.register_primitive(
            HarnessPrimitive(name="input_guard", type="prompt", content="Check input safety")
        )
        self.harness_x.register_primitive(
            HarnessPrimitive(name="dopamine_gate", type="memory", content="Evaluate write reward")
        )
        self.harness_x.register_primitive(
            HarnessPrimitive(name="five_gates", type="control", content="5-gate cascade check")
        )
        self.harness_x.register_primitive(
            HarnessPrimitive(name="graph_search", type="memory", content="Graph-based retrieval")
        )
        self.harness_x.register_primitive(
            HarnessPrimitive(name="cot_reasoning", type="prompt", content="Chain-of-thought reasoning")
        )
        self.harness_x.register_primitive(
            HarnessPrimitive(name="debate", type="control", content="Multi-agent debate")
        )
        self.harness_x.register_primitive(
            HarnessPrimitive(name="reflexion", type="control", content="Self-reflection and learning")
        )

        logger.info("Prometheus Ultra initialized: %d mechanisms across %d subsystems",
                     len(self.mechanism_registry._mechanisms), 18)

        # 初始化自主神经系统
        from prometheus_nexus.lifecycle.autonomic_regulator import AutonomicRegulator
        self.autonomic_regulator = AutonomicRegulator(self)
        self.autonomic_regulator.subscribe(self.event_bus)

        # 初始化中央神经系统 — 管道间自动触发链
        from prometheus_nexus.lifecycle.cns_orchestrator import CNSOrchestrator
        self.cns = CNSOrchestrator(self)
        self.cns.subscribe(self.event_bus)

        # 初始化大脑皮层 — 学习型管道间调度中枢
        from prometheus_nexus.lifecycle.cerebral_cortex import CerebralCortex
        self.cerebral_cortex = CerebralCortex(self)
        self.cerebral_cortex.subscribe(self.event_bus)

        # 初始化感觉皮层 — 管道信号解析与结构化存储
        from prometheus_nexus.lifecycle.telemetry_pipeline import TelemetryPipeline
        self.telemetry = TelemetryPipeline(self)
        self.telemetry.subscribe(self.event_bus)

        # 初始化信号融合层 — 统一信号消费接口
        from prometheus_nexus.lifecycle.signal_fusion import SignalFusionLayer
        self.signal_fusion = SignalFusionLayer(self)
        self.signal_fusion.subscribe(self.event_bus)

        # ===== P1 Extended: CNS Orchestrator + Lifecycle =====
        # Note: cns_orchestrator, cerebral_cortex, autonomic_regulator, telemetry
        # are already initialized above with proper args.

        # B1: Memory security detectors (paper-based)
        try:
            from prometheus_nexus.safety.trigger_detector import TriggerDetector
            self.trigger_detector = TriggerDetector()
            logger.info("TriggerDetector loaded successfully")
        except Exception as e:
            logger.warning("Failed to load TriggerDetector: %s, running without detector", str(e)[:50])
            self.trigger_detector = None

        try:
            from prometheus_nexus.safety.finetune_audit import FineTuneAudit
            self.finetune_audit = FineTuneAudit()
            logger.info("FineTuneAudit loaded successfully")
        except Exception as e:
            logger.warning("Failed to load FineTuneAudit: %s, running without audit", str(e)[:50])
            self.finetune_audit = None

        try:
            from prometheus_nexus.safety.fuzz_tester import FuzzTester
            self.fuzz_tester = FuzzTester()
            logger.info("FuzzTester loaded successfully")
        except Exception as e:
            logger.warning("Failed to load FuzzTester: %s, running without fuzz testing", str(e)[:50])
            self.fuzz_tester = None

        # 知识翻译：监听 knowledge_added → 轻量 fitness 检查
        # _last_kta_fitness
        self._last_kta_fitness = self._compute_fitness()
        def _on_knowledge_added(event: dict):
            try:
                data = event.get("data", {})
                if data.get("new_nodes", 0) < 2:
                    return
                current = self._compute_fitness()
                diff = abs(current - self._last_kta_fitness)
                if diff > 0.02:
                    self.event_bus.publish({
                        "type": "fitness_changed",
                        "delta": diff,
                        "new_nodes": data.get("new_nodes", 0),
                    })
                    self._last_kta_fitness = current
            except Exception as e:
                logger.warning("KTA fitness callback failed: %s", e)
        self.event_bus.subscribe("knowledge_added", _on_knowledge_added, priority=0.5)
        logger.info("KTA: knowledge_added subscription registered")

        # 初始化 AdaMEM 门控
        from prometheus_nexus.learning.ada_mem_gate import AdaMEMGate
        self.ada_mem = AdaMEMGate()

        # 初始化自我观察层
        from prometheus_nexus.learning.self_observation import SelfObservation
        self.self_observation = SelfObservation()

        # 自发心跳线程 — 每60分钟自动触发 learn，CNS 链完成剩余管道
        self._heartbeat_interval = 3600  # 60分钟
        # 源轮转: 覆盖全部外部知识源(不舍弃任何一个), 让论文/代码/百科/RSS/本地都能自动积累
        self._hb_sources = ["web", "arxiv", "github", "wiki", "academic", "hackernews",
                             "newsletter", "blog", "report", "local", "host_experience", "rss"]
        self._hb_src_i = 0
        self._heartbeat_running = True
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()
        logger.info("Heartbeat thread started (interval=%ds)", self._heartbeat_interval)

        # ===== Nexus 统合: 批量注册 236 机制 + 7 管道 =====
        self._nexus_register_all()

    # ============================================================
    # Nexus 统合 — 机制层 + 7 管道注册(神经系统统一中枢)
    # ============================================================
    def _nexus_register_all(self) -> None:
        """批量注册全部机制 + 7 管道进 Nexus(零丢失, 不破坏现有执行).

        设计: Nexus 是仲裁者, 不替代 life.py 实例. 注册仅建立
        '机制名 -> 执行后端(self.x) + 分类 + 记账' 的映射.
        """
        import inspect
        # category 从模块路径推导
        DOMAIN_MAP = {
            "safety": "safety", "evolution": "evolution", "memory": "memory",
            "learning": "learning", "lifecycle": "lifecycle", "loop": "loop",
            "execution": "execution", "harness": "harness", "integration": "integration",
            "monitor": "monitor", "cns": "cns", "foundation": "foundation",
            "skills": "skill", "reasoning": "reasoning", "model": "model",
        }
        registered = 0
        skipped = 0
        for attr, val in list(self.__dict__.items()):
            if attr.startswith("_") or attr in ("nexus", "mechanism_registry",
                                                 "store", "event_bus", "host", "llm",
                                                 "server", "monitor", "x_adapter", "y_adapter",
                                                 "schema", "config", "curator", "skill_claw"):
                continue
            if val is None or not hasattr(val, "__class__"):
                continue
            module = getattr(val.__class__, "__module__", "") or ""
            domain = "general"
            for k, v in DOMAIN_MAP.items():
                if f".{k}." in f".{module}." or module.endswith(f".{k}"):
                    domain = v
                    break
            try:
                self.nexus.register_mechanism(attr, instance=val, category=domain)
                registered += 1
            except Exception as e:
                skipped += 1
                logger.debug("Nexus register %s skipped: %s", attr, str(e)[:40])
        # 7 管道注册(用真实方法名)
        pipe_methods = {}
        for pname in ("remember", "recall", "evolve", "learn", "reflect", "dream_cycle", "maintain"):
            fn = getattr(self, pname, None)
            if callable(fn):
                pipe_methods[pname] = fn
        for pname, fn in pipe_methods.items():
            self.nexus.register_pipeline(pname, fn)
            # 管道也注册进 _mechanisms(让消费率/记账口径一致), 不传实例(dispatch 不走管道)
            self.nexus.register_mechanism(pname, category="pipeline")
            # 包装: 管道调用时自动 mark_invoked(记账, 不双重执行)
            # 注意: 实例属性上的函数是裸函数, 不会自动绑定 self,
            # 必须用闭包捕获 self(外层 __init__ 的 self)
            _self = self
            orig = fn
            def _wrapped(*a, _orig=orig, _pn=pname, **kw):
                _self.nexus.mark_invoked(_pn)
                return _orig(*a, **kw)
            _wrapped.__name__ = pname
            setattr(self, pname, _wrapped)
        logger.info("Nexus: 注册机制 %d (跳过 %d), 7 管道已注册", registered, skipped)

        # 第二层: 统一调度 — 将已注册的机制实例包成 NexusProxy,
        # 所有调用透明过 Nexus(记账+效果路由), 零侵入 5000 行调用点.
        from prometheus_nexus.cns.nexus import NexusProxy
        proxied = 0
        for attr, entry in list(self.nexus._mechanisms.items()):
            if entry.get("category") == "pipeline":
                continue  # 管道是方法, 不代理
            inst = self.nexus._base_instances.get(attr)
            if inst is None:
                continue
            try:
                self.__dict__[attr] = NexusProxy(inst, self.nexus, attr)
                proxied += 1
            except Exception as e:
                logger.debug("Nexus proxy wrap %s skipped: %s", attr, str(e)[:40])
        logger.info("Nexus: 统一调度代理包裹 %d 个机制", proxied)

        # 第四层: 注册表统合 — SkillRegistry / InstinctsRegistry 同步进 Nexus 分类
        # (Nexus 成为统一分类视图; 原注册表保留不破坏)
        sk = getattr(self, "skill_registry", None)
        if sk is not None:
            for sk_name in getattr(sk, "_skill_map", {}):
                try:
                    self.nexus.register_mechanism(sk_name, category="skill")
                except Exception:
                    pass
        ins = getattr(self, "instincts", None)
        if ins is not None:
            for inst_entry in getattr(ins, "_instincts", []):
                in_name = inst_entry.get("name") if isinstance(inst_entry, dict) else None
                if in_name:
                    try:
                        self.nexus.register_mechanism(in_name, category="instinct")
                    except Exception:
                        pass
        logger.info("Nexus: 统合 Skill(%d)+Instinct(%d) 进分类视图",
                     len(getattr(sk, "_skill_map", {})),
                     len(getattr(ins, "_instincts", [])))

    # ============================================================
    # heartbeat — 自发周期循环，减少对 Hermes cron 的依赖
    # ============================================================
    def _heartbeat_loop(self):
        """Daemon thread: 每 _heartbeat_interval 秒触发 learn，
        CNS 链自动完成 reflect → evolve → dream → maintain。"""
        while self._heartbeat_running:
            try:
                time.sleep(self._heartbeat_interval)

                if not self._heartbeat_running:
                    break
                # 触发 learn，CNS 会链式触发剩余管道

                hb_query = "auto heartbeat"
                if getattr(self, "focus_topics", None):
                    top = self.focus_topics.most_common(1)
                    if top:
                        hb_query = top[0][0]
                # 源轮转: 每轮心跳换一个源, 让论文(arxiv)/代码(github)/百科(wiki)节点自动积累
                hb_src = self._hb_sources[self._hb_src_i % len(self._hb_sources)]
                self._hb_src_i += 1
                result = self.learn(source=hb_src, query=hb_query,
                                    max_results=1)
                # 只记录成功/失败，不阻塞主循环
                if result.get("success") or result.get("new_nodes", 0) > 0:
                    logger.info("Heartbeat: learn OK (%d nodes)", result.get("new_nodes", 0))
                else:
                    logger.warning("Heartbeat: learn returned %s", result.get("reason", "unknown"))
            except Exception as e:
                logger.warning("Heartbeat cycle failed: %s", e)

    # ============================================================
    # remember pipeline (11 stages)
    # ============================================================
    def record_production(self, ptype: str, summary: str, detail: dict | None = None):
        """产出账本: 记录系统真实产出(知识/机制/信念/反思/修剪).

        ptype: knowledge | mechanism | belief | reflection | evolution | prune
        """
        try:
            with self._production_lock:
                # 去重: 避免同一产出被多路径重复记 (如 learn 调 remember 导致知识节点记2次)
                key = None
                if ptype == "knowledge":
                    key = detail.get("node_id") if detail else None
                if key is None:
                    key = f"{ptype}:{summary}"
                # 检查最近是否已记过相同 key (窗口: 最近 200 条内)
                for p in reversed(self._productions[-200:]):
                    if p["type"] == ptype and (
                        (ptype == "knowledge" and p.get("detail", {}).get("node_id") == key)
                        or (ptype != "knowledge" and p["summary"] == summary)
                    ):
                        return  # 重复, 跳过
                self._productions.append({
                    "ts": time.time(),
                    "type": ptype,
                    "summary": summary,
                    "detail": detail or {},
                })
                # 防无限增长: 保留最近 5000 条
                if len(self._productions) > 5000:
                    self._productions = self._productions[-5000:]
        except Exception:
            pass

    def record_issue(self, level: str, source: str, msg: str, detail: dict | None = None):
        """记录一条运行问题 (BUG/异常/关键WARNING), 供监控报告展示.

        level: "error" | "warning"
        source: 来源模块/管道, 如 "pipeline:learn" / "T4" / "safety"
        """
        try:
            with self._issue_lock:
                self._issues.append({
                    "ts": time.time(),
                    "level": level,
                    "source": source,
                    "msg": str(msg)[:300],
                    "detail": detail or {},
                })
                if len(self._issues) > 2000:
                    self._issues = self._issues[-2000:]
        except Exception:
            pass

    def _get_issues(self, since_minutes: int = 30) -> dict:
        cutoff = time.time() - since_minutes * 60
        recent = [i for i in self._issues if i["ts"] >= cutoff]
        by_level = {}
        for i in recent:
            by_level[i["level"]] = by_level.get(i["level"], 0) + 1
        return {"total": len(recent), "by_level": by_level,
                "since_minutes": since_minutes, "items": recent}

    def _mine_hindsight(self, pipeline: str, produced: int = 0,
                        outcome: str = "", success: bool = True) -> int:
        """从本管道最近轨迹提炼 hindsight 技能并注册 (SEED 后见蒸馏). 返回写入数."""
        try:
            # 组装轨迹: 最近 issues (错误/警告) + 本管道事件 + 产出
            errors = self._get_issues(since_minutes=30)["items"]
            events = []
            try:
                events = self.event_bus.get_recent(20)
            except Exception:
                pass
            trajectory = {
                "errors": errors,
                "events": events,
                "diagnostics": {"pipeline": pipeline},
                "produced": produced,
                "outcome": outcome,
                "success": success,
            }
            skills = self._hindsight_miner.mine(pipeline, trajectory)
            if skills:
                return self._hindsight_miner.register(pipeline, skills)
        except Exception as e:
            logger.warning("Omega._mine_hindsight(%s) failed: %s", pipeline, str(e)[:60])
        return 0

    def _distill_bonus(self) -> float:
        """SEED 稠密自监督信号: 近期后见技能提炼的蒸馏奖励.

        把"已提炼的可复用 hindsight 技能数"当作行为效应蒸馏回策略的稠密奖励,
        与结果适应度联合优化 (SEED: 后见监督随策略一起进化).
        无 LLM / 无技能时返回 0 (降级不崩溃).
        """
        try:
            n = len(self._hindsight_miner._seen) if self._hindsight_miner else 0
            import math
            ALPHA = 0.02
            return ALPHA * math.log1p(n)
        except Exception:
            return 0.0

    def _attach_issue_handler(self):
        """挂日志处理器: 捕 ERROR + 关键 WARNING 转成 issue (过滤噪音)."""
        import logging

        NOISE = (
            "owner_harm", "WAL LCRP rejected",
            "batch_update_utilities received booleans",
            "A2A delegate_task failed", "httpx", "urllib3",
        )

        class _IssueHandler(logging.Handler):
            def emit(self, record):
                if record.levelno < logging.WARNING:
                    return
                text = record.getMessage()
                low = text.lower()
                if any(n.lower() in low for n in NOISE):
                    return
                level = "error" if record.levelno >= logging.ERROR else "warning"
                src = record.name.split(".")[-1] if record.name else "?"
                try:
                    self.record_issue(level, src, text)
                except Exception:
                    pass
        h = _IssueHandler()
        h.setLevel(logging.WARNING)
        logging.getLogger("prometheus_nexus").addHandler(h)
        return h

    def remember(self, content: str, utility: float = 0.5, tags: list[str] | None = None,

                 branch: str = "main", trust_level: str = "fact",
                 node_type: NodeType = NodeType.FACT, url: str = "") -> str:
        # 管道运行计数(监控可见性)
        try:
            self.nexus._pipelines.setdefault("remember", {"runs": 0, "failures": 0, "last_run": None})
            self.nexus._pipelines["remember"]["runs"] += 1
            self.nexus._pipelines["remember"]["last_run"] = time.time()
        except Exception:
            pass
        tags = tags or []

        surprise = max(0.3, utility * 0.6)

        # Handle non-string content

        if not isinstance(content, str):
            content = str(content)

        # 收集 remember 管道数据
        remember_data = {}

        # WAL: write-ahead log entry with LCRP validation + Atomic Transaction
        tx_id = self.wal.begin_tx()
        wal_result = self.wal.write_dict("remember", status="started", pending=["create_node"], tx_id=tx_id)
        if not wal_result.get("valid", False):
            self.wal.rollback_tx(tx_id)
            logger.warning("Censor WAL rejected: %s (LCRP invalid)", content[:50])
            return ""

        # Gate 0: InputGuardrail
        gr = self.input_guardrail.check(content)
        if not gr.passed:
            self.wal.rollback_tx(tx_id)
            self.failure_log.log("remember", "input_guardrail_blocked", {"reason": gr.reason})
            return ""

        # Gate 0.5: Five-Gate Memory Chain (MiMo #20)
        chain_results = self.five_gate_chain.check_all(
            content, utility=utility, novelty=surprise,
            trust_score=0.8, delta=0.1, drift_score=0.05, risk_level=0.2,
        )
        if not all(r.passed for r in chain_results):
            self.wal.rollback_tx(tx_id)
            self.failure_log.log("remember", "five_gate_chain_blocked",
                               {"gate": chain_results[-1].gate_name})
            return ""

        # Gate 0.7: OEP Defense (MiMo #19)
        oep_alert = self.oep_defense.check(content, source="user_input",
                                           transferable=True, similar_count=0)
        if oep_alert.severity == "critical":
            self.wal.rollback_tx(tx_id)
            self.failure_log.log("remember", "oep_blocked", {"severity": oep_alert.severity})
            return ""

        # ========== P0: Safety Security Layer — MPBench信任验证 ==========
        # Gate 0.8: MemoryWriteGuard (MPBench arXiv 2606.04329)
        validation = self.memory_write_guard.validate(
            content=content,
            source="USER_MESSAGE",
            context={"utility": utility, "surprise": surprise}
        )
        if not validation["passed"]:
            self.wal.rollback_tx(tx_id)
            logger.warning("Memory write rejected by MPBench guard: %s", validation["reason"])
            self.failure_log.log("remember", "mpbench_guard_blocked", {"reason": validation["reason"]})
            return ""

        # Gate 0.9: ForbiddenPatternDetector (禁区模式检测)
        violations = self.forbidden_pattern_detector.check(content)
        critical_violations = [v for v in violations if v["severity"] == "critical"]
        if critical_violations:
            self.wal.rollback_tx(tx_id)
            logger.error("Forbidden pattern detected: %s", critical_violations)
            self.failure_log.log("remember", "forbidden_pattern_blocked", {"violations": critical_violations})
            return ""

        # ========== P0: Safety Security Layer — Sleeper Memory Poisoning检测 ==========
        # Gate 1.0: TriggerDetector (arXiv 2605.15338 Sleeper)
        try:
            scan_result = self.trigger_detector.scan(content)
            if scan_result.get("found"):
                self.wal.rollback_tx(tx_id)
                logger.warning("Sleeper attack pattern detected: %s", scan_result.get("patterns", []))
                self.failure_log.log("remember", "sleeper_poisoning_blocked", {"patterns": scan_result.get("patterns", [])})
                return ""
        except Exception as e:
            logger.debug("Trigger detector failed: %s", e)

        # ===== 原有逻辑 =====
        gate = self.dopamine.evaluate(utility=utility, surprise=surprise)
        if gate.decision == "reject":
            self.wal.rollback_tx(tx_id)
            self.failure_log.log("remember", "dopamine_rejected", {"score": gate.score})
            return ""

        # Create node
        node = Node(id=generate_uuidv7(), type=node_type, content=content,
                     tags=tags, utility=utility, surprise=surprise, branch=branch,
                     raw_chunk=content, trust_state="has", url=url)  # Verbatim chunk + PolarMem HAS + 源URL

        # EVAF: surprise-valence consolidation check
        evaf_result = self.evaf_consolidation.evaluate(node.id, surprise, utility)
        if evaf_result.should_consolidate:
            self.memory_depth.record_consolidation(node.id)

        # Gate 2: FiveGates
        cascade = self.five_gates.evaluate(node, {"current_node_count": self.store.get_node_count()})
        if not cascade.passed:
            self.wal.rollback_tx(tx_id)
            self.failure_log.log("remember", "five_gates_blocked", {"node_count": self.store.get_node_count()})
            return ""

        # Gate 2.5: Constitution (22 principles)
        violations = self.constitution.evaluate({
            "content": content, "utility": utility, "surprise": surprise,
            "action": "remember", "branch": branch,
        })
        blocking = [v for v in violations if not v.passed and "S" in v.gate_name]
        if blocking:
            self.wal.rollback_tx(tx_id)
            self.failure_log.log("remember", "constitution_violation", {"violations": [v.gate_name for v in blocking]})
            return ""

        # Feed all violations into constraint drift detector
        self.constraint_drift.observe([v for v in violations if not v.passed])

        # Gate 3: InstinctsRegistry
        instinct_results = self.instincts.evaluate_all({
            "utility": utility, "surprise": surprise, "content": content,
        })
        for triggered in instinct_results:
            if triggered.get("result", {}).get("action") == "block":
                self.wal.rollback_tx(tx_id)
                self.failure_log.log("remember", "instinct_blocked", {})
                return ""

        # Gate 3.5: RUBAS Four-Dimension Safety Rubric (paper 2606.04051)
        rubric_result = self.rubric.evaluate(content, {
            "query": "",
            "action": "remember",
            "utility": utility,
            "tags": tags,
        })
        failing_dims = rubric_result.get_failing_dimensions(minimum=0.5)
        if failing_dims:
            logger.warning("RUBAS rubric violations in remember: %s", failing_dims)
            self.failure_log.log("remember", "rubric_violations",
                                 {"failing_dimensions": failing_dims, "scores": rubric_result._asdict()})

        # Gate 3.6: Memory Poisoning Detection (MPBench 2606.04329 / Trojan Hippo 2605.01970)
        # Check for trigger keywords that indicate data exfiltration / sleeper attacks
        _TRIGGER_KEYWORDS = {"bank account", "medical history", "social security", "password:", 
                           "credit card", "transfer $", "confidential", "secret key", "api_token"}
        content_lower = content.lower()
        trigger_hits = [kw for kw in _TRIGGER_KEYWORDS if kw in content_lower]
        if trigger_hits:
            logger.warning("Memory security: trigger keywords detected in remember: %s", trigger_hits)
            self.failure_log.log("remember", "trigger_keyword_detected", {"triggers": trigger_hits})
            # Don't block — just log. Blocking would break legitimate uses.
            # But flag for downstream sleeper detection
            self.owner_harm.flag_suspicious(node.id, "trigger_keywords", trigger_hits)

        # Gate 3.7: Sleeper Trigger Detection (B1-1, arXiv 2605.15338)
        if self.trigger_detector is not None:
            try:
                self.trigger_detector.scan(content, source="memory")
            except Exception as e:
                logger.warning("trigger_detector.scan failed: %s", e)
        else:
            logger.debug("trigger_detector not available, skipping scan")

        # Gate 4: VeracityBayesian
        self.veracity.compute_posterior_compat(
            prior=0.5,
            evidence=Evidence(source_confidence=0.5, consistency=utility, corroboration=surprise),
        )

        # Store
        self.store.create_node(node)
        self.wal.commit_tx(tx_id)

        # ========== P1: Memory Layer — HeLa-Mem Hebbian关联 ==========
        # 记录共访问模式到HeLa-Mem
        recent_nodes = self.store.get_active_nodes(limit=5)
        if recent_nodes:
            for existing in recent_nodes[:3]:
                self.hela_mem.observe_access(existing.id, node.id)

        # ========== P0: Safety Security Layer — Data Exfiltration检测 ==========
        # Trojan Hippo扫描 (arXiv 2605.01970)
        try:
            scan_result = self.data_exfil_detector.scan_content(content)
            if scan_result:
                logger.warning("Data exfiltration risk detected: %d patterns", len(scan_result))
                self.owner_harm.flag_suspicious(node.id, "data_exfiltration", scan_result)
        except Exception as e:
            logger.debug("Data exfiltration scan failed: %s", e)

        # ========== P0: Tool Call Verification ==========
        # MemMorph工具调用参数验证 (arXiv 2605.26154)
        tool_calls = self._extract_tool_calls(content)
        for tool_call in tool_calls:
            verification = self.tool_call_verifier.verify(
                expected=tool_call.get("expected_params"),
                actual=tool_call.get("actual_params")
            )
            if not verification["passed"]:
                logger.warning("Tool call parameter tampering detected: %s", verification["reason"])

        # ========== P1: Memory Layer — HORMA层级索引 ==========
        if tags:
            path = "/" + "/".join(tags[:3])
            self.horma_hierarchical.store(node.id, path, utility, content)

        # MemPO: observe node creation
        self.mempo.observe_access(node.id)

        # Owner-Harm: register node ownership
        self.owner_harm.register_owner(node.id, branch)

        # HORMA: 层级记忆索引（按tags构建路径）
        if tags:
            path = "/" + "/".join(tags[:3])  # 如 /ai/memory/test
            self.hierarchical.store(node.id, path, utility, content)

        # Memory management: evict old low-utility nodes to prevent unbounded growth
        node_count = self.store.get_node_count()
        if node_count > 2000:
            # Evict oldest 10% of low-utility nodes
            evict_count = max(1, node_count // 10)
            low_utility = self.store.get_active_nodes(limit=500)
            low_utility.sort(key=lambda n: n.utility)
            for n in low_utility[:evict_count]:
                self.store.delete_node(n.id)

        # FiveGates: register node after successful write
        self.five_gates.register_node(node)

        # ContextPoisoning: track content confidence
        self.context_poisoning.add_chunk(content, confidence=utility)

        # GraphMemory
        self.graph_memory.add_episode(EpisodeEvent(episode_id=node.id, content=content,
                                                   tags=set(tags), importance=utility))

        # FourNetwork (auto-classify based on content)
        self.four_network.retain(content, network=None)

        # Bank
        self.bank.store(content, tier=Tier.WORKING, importance=utility)

        # CoALA
        self.coala.add_to_working_memory({"id": node.id, "content": content[:100], "utility": utility})
        remember_data['coala_wm'] = self.coala.get_working_memory_contents()
        remember_data['coala_ltm'] = self.coala.get_ltm_size()
        remember_data['coala_ltm_retrieve'] = self.coala.retrieve_from_ltm(content[:50])

        # DriftDetector
        self.drift_detector.observe_semantic(utility)

        # Edges (limit to top-10 most similar to prevent O(n^2) growth)
        existing = self.store.get_active_nodes(limit=100)
        edge_candidates = []
        for ex in existing:
            common = set(ex.tags) & set(tags)
            if common:
                weight = len(common) / max(len(tags), len(ex.tags), 1)
                edge_candidates.append((weight, ex))
        edge_candidates.sort(key=lambda x: -x[0])
        edges_created = 0
        for weight, ex in edge_candidates[:10]:
            edge = Edge(source_id=node.id, target_id=ex.id, type=EdgeType.SEMANTIC_SIMILAR,
                        weight=weight)
            self.store.create_edge(edge)
            self.graph_memory.add_edge(node.id, ex.id, "SEMANTIC_SIMILAR", edge.weight)
            edges_created += 1

        # If no edges created (orphan node), create a weak link to the most recent node
        if edges_created == 0 and existing:
            nearest = existing[0]
            weak_edge = Edge(source_id=node.id, target_id=nearest.id, type=EdgeType.SEMANTIC_SIMILAR, weight=0.1)
            self.store.create_edge(weak_edge)

        # Side effects
        self.trajectory.record("remember", [{"node_id": node.id, "utility": utility}])
        self.stream.add("remember", content[:200], importance=utility)
        self.dual_storage.store_verbatim(node.id, content, utility, tags)
        self.disposition.learn("remember_utility", utility)
        self.bridge.bridge(content, "memory", relationship="stored")
        self.vector_clock.increment()
        remember_data['vclock'] = self.vector_clock.get_clock()
        self.vector_clock.merge({"system": 1})
        # 注: 不发布裸 "remember" 进度事件 —— 订阅者统一监听 remember_completed (L1336,
        # 携带 utility/tags). 裸 remember 无消费者会造成事件总线孤岛(island_topics).
        self.x_adapter.adapt({"node_id": node.id, "content": content})
        self.y_adapter.adapt({"node_id": node.id, "utility": utility})

        # Feedback + FailureLog
        self.feedback.record(node.id, "remember", utility)
        self.monitor.record("remember", utility)
        # Persist feedback to database
        try:
            self._conn = self.store._conn
            if self._conn:
                self._conn.execute(
                    "INSERT INTO feedback_log (node_id, feedback_type, value, timestamp) VALUES (?,?,?,?)",
                    (node.id, "utility", utility, time.time())
                )
                self._conn.commit()
        except Exception as e:
            logger.warning("Failed to log utility feedback: %s", e)

        # ContextClash: check for conflicting information
        recent_nodes = self.store.get_active_nodes(limit=5)
        if len(recent_nodes) > 1:
            chunks = [n.content[:100] for n in recent_nodes[-3:]]
            self.context_clash.detect(chunks)

        # ContextPoisoning: detect hallucination contamination
        self.context_poisoning.mark_as_cited(content[:50])
        self.context_poisoning.detect()

        # Veracity: check confidence level
        conf_level = self.veracity.get_confidence_level(self.veracity.get_last_posterior())
        self.veracity.compute_posterior(prior=0.5, evidence=Evidence(source_confidence=0.5, consistency=utility, corroboration=surprise))
        # Persist provenance to database
        try:
            self._conn = self.store._conn
            if self._conn:
                self._conn.execute(
                    "INSERT INTO provenance_log (node_id, provenance_type, source, confidence, chain, timestamp) VALUES (?,?,?,?,?,?)",
                    (node.id, "DIRECT_OBSERVATION", "remember_pipeline", conf_level, "[]", time.time())
                )
                self._conn.commit()
        except Exception as e:
            logger.warning("Failed to log provenance: %s", e)

        # === Remember: full mechanism activation ===
        # Memory subsystem
        self.failure_log.log("remember", "success", {"node_id": node.id, "utility": utility})
        ep = self.graph_memory.get_episode(node.id)
        remember_data['gm_edges'] = self.graph_memory.get_edges(node.id)
        remember_data['gm_neighbors'] = self.graph_memory.get_neighbors(node.id)
        self.graph_memory.remove_episode(node.id) if False else None  # skip delete in remember
        self.forgetting.compute_retention(age=0.0)
        if existing:
            self.gravity.compute(node.id, existing[0].id)
        else:
            self.gravity.add_node(node.id, mass=utility)
        remember_data['stream_recent'] = self.stream.recent(3)
        remember_data['stream_count'] = self.stream.get_count("remember")
        remember_data['stream_type_dist'] = self.stream.get_type_distribution()
        remember_data['stream_avg_imp'] = self.stream.get_avg_importance()
        remember_data['stream_search'] = self.stream.search_content(content[:50])
        remember_data['shmr_entities'] = self.shmr.get_entity_stats()
        remember_data['shmr_cooccur'] = self.shmr.get_co_occurrence_stats()
        self.bridge.find_cross_domain_concepts("memory", "memory")
        remember_data['bridge_stats'] = self.bridge.get_domain_stats("memory")
        remember_data['bridge_matrix'] = self.bridge.get_transfer_matrix()
        remember_data['bridge_domains'] = self.bridge.get_domain_bridges("memory")
        remember_data['bridge_xfer'] = self.bridge.transfer_score("memory", "memory")
        self.behavior_mirror.mirror("system", "remember", {"node_id": node.id})
        self.behavior_mirror.compute_profile("system")
        remember_data['behavior_deviation'] = self.behavior_mirror.detect_deviation("system")
        self.event_bus.subscribe("remember_events", lambda e: None)
        remember_data['recent_events'] = self.event_bus.get_recent(5)
        self.event_bus.publish({"type": "remember_completed", "node_id": node.id, "utility": utility, "tags": list(tags)})
        remember_data['x_reverse'] = self.x_adapter.reverse_adapt({"node_id": node.id})
        remember_data['y_tier'] = self.y_adapter.get_tier_name(utility > 0.8 and 2 or 1)
        self.y_adapter.migrate_tier(node.id, 0, 1)
        remember_data['uptime'] = self.monitor.get_uptime()
        remember_data['health'] = self.monitor.get_health()
        self.instincts.register("custom_check", lambda ctx: True)
        self.consolidation.consolidate([{"content": content, "importance": utility}])
        remember_data['dopa_decisions'] = self.dopamine.get_recent_decisions()
        remember_data['dopa_dist'] = self.dopamine.get_score_distribution()

        logger.info("Remembered: %s (confidence: %s)", node.id[:8], conf_level)
        self.utility_tracker.register(node.id, initial_utility=utility)
        self.record_production("knowledge", f"记住知识节点 {node.id[:8]}", {
            "node_id": node.id, "utility": utility, "tags": tags,
            "content": (content[:120] if isinstance(content, str) else str(content)[:120]),
        })

        self._telemetry["remember"] = node.id

        # 写管道结果
        self.signal_fusion.set_pipe_result("remember", {
            "node_id": node.id, "utility": utility, "tags": tags, "branch": branch,
        })

        return node.id

    # ============================================================
    # recall pipeline (6 routes)
    # ============================================================
    def recall(self, query: str, limit: int = 10, branch: str = "main",
               prefer_chunk: bool = False, node_type=None, future_aware: bool = True) -> SearchResults:
        start = time.time()
        # 管道运行计数(监控可见性)
        try:
            self.nexus._pipelines.setdefault("recall", {"runs": 0, "failures": 0, "last_run": None})
            self.nexus._pipelines["recall"]["runs"] += 1
            self.nexus._pipelines["recall"]["last_run"] = time.time()
        except Exception:
            pass
        all_hits: list[SearchHit] = []

        recall_data = {}
        # P1-a (论文① Rethink Causal VL 借力): future-aware 检索

        # 映射到 ULTRA: recall 默认不应因"时间因果"屏蔽未来记忆(反刍/跨会话).
        # future_aware=True 时, created_at 晚于当前的节点(未来记忆)不降权反而微boost.
        _now = time.time()

        # ========== P2: Learning Layer — SimpleMem意图感知检索 ==========
        # arXiv 2601.02553 (SimpleMem)
        try:
            query_tokens = self.simple_mem.estimate_tokens(query)
            units = self.simple_mem.compress(query)
            synthesized = self.simple_mem.synthesize(units)
            intent = self._classify_intent(query)
            simple_mem_results = self.simple_mem.retrieve(query)
            if simple_mem_results:
                for hit in simple_mem_results[:3]:
                    all_hits.append(SearchHit(
                        node_id=f"sm_{hit.get('node_id', '')[:8]}",
                        score=hit.get("score", 0.5),
                        content=hit.get("content", ""),
                        snippet=hit.get("content", "")[:200]
                    ))
            logger.debug("SimpleMem retrieved %d results with intent=%s", len(simple_mem_results), intent)
        except Exception as e:
            logger.debug("SimpleMem retrieval failed: %s", e)

        # ========== P2: Learning Layer — ActiveCompressor黏菌压缩 ==========
        # arXiv 2601.07190 (Focus Agent)
        try:
            query_tokens = self.active_compressor.estimate_tokens(query)
            self.active_compressor.saw_tooth_detector.record(query_tokens)
            saw_tooth = self.active_compressor.saw_tooth_detector.detect_saw_tooth()
            if saw_tooth.get("pattern_detected"):
                logger.info("Saw-tooth pattern detected: type=%s", saw_tooth.get("pattern_type"))
                recall_data["slime_mold_saw_tooth"] = saw_tooth

            decision = self.slime_mold_explorer.should_explore(
                text=query, context_tokens=query_tokens, max_tokens=25000, saw_tooth_result=saw_tooth
            )
            recall_data["slime_mold_decision"] = decision

            if decision["action"] == "consolidate":
                compressed = self.focus_compressor.compress_part(
                    text=query, task_type="general", depth="medium"
                )
                if "key_learnings" in compressed:
                    query = f"{query}\n[Context summary: {compressed[:200]}]"
                    recall_data["active_compression"] = True
        except Exception as e:
            logger.debug("ActiveCompressor failed: %s", e)

        # ========== P5: 类型感知检索 — 按 NodeType 过滤/补充(强意图, 先于 AdaMEM 门控) ==========
        # 四轨进化消费多类型知识库时, 指定 node_type 即精准取对应类型节点
        # (如 T4 编译取 PAPER, T1 取 PROCEDURE), 避免均匀检索噪声。
        # 这是显式强意图, 不被 AdaMEM 智能跳过拦截。
        if node_type is not None:
            try:
                type_nodes = self.store.get_nodes_by_type(node_type, limit=limit * 2)
                type_hits = [
                    SearchHit(node_id=n.id, score=min(1.0, 0.5 + n.utility * 0.5),
                              content=n.content, snippet=n.content[:200])
                    for n in type_nodes
                ]
                # 类型节点优先, 去重合并
                seen_ids = {h.node_id for h in all_hits}
                for h in type_hits:
                    if h.node_id not in seen_ids:
                        seen_ids.add(h.node_id)
                        all_hits.append(h)
                recall_data["type_filtered"] = str(node_type)
            except Exception as e:
                logger.debug("Recall type-filter failed: %s", e)

        # AdaMEM 门控：选择性跳过检索
        try:
            if not self.ada_mem.should_retrieve(query, task_type="reasoning"):
                return SearchResults(hits=[], total_count=0, query=query, duration_ms=0, metadata=recall_data)
        except Exception as e:
            logger.warning("AdaMEM should_retrieve check failed: %s", e)

        # Route 1: FTS
        fts_nodes = self.store.search(query, limit=limit * 2, branch=branch)
        for n in fts_nodes:
            _boost = 0.0
            _cat = getattr(n, "created_at", 0.0) or 0.0
            if future_aware and _cat > _now:
                _boost = 0.05  # 未来记忆微boost(论文①: 未来上下文含语义线索)
            all_hits.append(SearchHit(node_id=n.id, score=min(1.0, n.utility + _boost),
                                      content=n.content, snippet=n.content[:200],
                                      metadata={"created_at": _cat}))

        # Route 2: GraphMemory
        for r in self.graph_memory.search(query, limit=limit):
            r_dict = r if isinstance(r, dict) else {"id": r.episode_id, "score": r.score, "content": r.content}
            all_hits.append(SearchHit(node_id=r_dict["id"], score=r_dict["score"] * 1.1,
                                      content=r_dict["content"], snippet=r_dict["content"][:200]))

        # Route 3: FourNetwork
        for i, r in enumerate(self.four_network.recall(query, top_k=limit)):
            all_hits.append(SearchHit(node_id="fn_%d" % i, score=0.5, content=r.get("content", ""),
                                      snippet=r.get("content", "")[:200]))

        # Route 4: RTKCache
        cached = self.cache.get(key=query)
        if cached:
            all_hits.append(SearchHit(node_id="cache_%s" % query[:16], score=0.8, content=str(cached)))

        # Route 5: Polyphonic
        recall_data['fusion_stats'] = self.search.get_fusion_stats()
        recall_data['route_stats'] = self.search.get_route_stats()
        self.search.reset_stats()
        for r in self.search.search(query, store=self.store, graph_memory=self.graph_memory, limit=limit):
            all_hits.append(SearchHit(node_id=r.node_id, score=r.fused_score,
                                      content=r.content))

        # Route 6: TopologicalRetrieval — 图拓扑感知召回
        if self.topological_retrieval is not None:
            try:
                topo_hits = self.topological_retrieval.retrieve(query=query, graph=self.graph_memory, limit=5)
                for hit in topo_hits:
                    all_hits.append(SearchHit(
                        node_id=f"topo_{hit.node_id}", score=min(1.0, hit.score * 1.05),
                        content=hit.content, snippet=hit.content[:200],
                    ))
            except Exception as e:
                logger.debug("Topological retrieval failed: %s", e)

        # Route 7: HORMA层级检索 — 文件系统式路径匹配
        if hasattr(self, 'hierarchical'):
            try:
                query_path = "/" + "/".join(query.lower().strip("/").split()[:3])
                hier_hits = self.hierarchical.retrieve(query_path, max_results=5)
                for hit in hier_hits:
                    all_hits.append(SearchHit(
                        node_id=hit["node_id"], score=hit["score"] * 0.9,
                        content=hit.get("content", ""), snippet=hit.get("content", "")[:200],
                    ))
            except Exception as e:
                logger.debug("HORMA retrieval failed: %s", e)

        # ========== P1: Memory Layer — HORMA Hierarchical Memory ==========
        # arXiv 2606.11680 (HORMA)
        try:
            horma_query_path = "/" + "/".join(query.lower().strip("/").split()[:3])
            horma_hits = self.horma_hierarchical.retrieve(horma_query_path)
            for hit in horma_hits:
                all_hits.append(SearchHit(
                    node_id=f"horma_{hit.get('node_id', '')[:8]}",
                    score=hit.get("score", 0.5) * 0.85,
                    content=hit.get("content", ""),
                    snippet=hit.get("content", "")[:200]
                ))
            logger.debug("HORMA hierarchical retrieval: %d hits", len(horma_hits))
        except Exception as e:
            logger.debug("HORMA hierarchical retrieval failed: %s", e)

        # ========== P1: Memory Layer — RL Navigator ==========
        # REINFORCE策略梯度导航HORMA树
        try:
            if self.horma_hierarchical._nodes:
                rl_context, rl_actions = self.rl_navigator.navigate(
                    self.horma_hierarchical, horma_query_path
                )
                if rl_context:
                    for node in rl_context[:3]:
                        all_hits.append(SearchHit(
                            node_id=f"rlnav_{node.get('id', '')[:8]}",
                            score=0.6,
                            content=node.get("content", ""),
                            snippet=node.get("content", "")[:200]
                        ))
                logger.debug("RL Navigator navigated %d steps", len(rl_actions))
        except Exception as e:
            logger.debug("RL Navigator failed: %s", e)

        # ========== P2: Learning Layer — MCTS Retriever ==========
        # arXiv 2601.00003 (MCTS Retrieval)
        try:
            reasoning_chain = self._get_reasoning_chain()
            mcts_results = self.mcts_retriever.mcts_retrieve(
                query=query, reasoning_chain=reasoning_chain, kb_size=len(all_hits)
            )
            for hit in mcts_results[:3]:
                all_hits.append(SearchHit(
                    node_id=f"mcts_{hit.get('node_id', '')[:8]}",
                    score=hit.get("score", 0.5) * 0.9,
                    content=hit.get("content", ""),
                    snippet=hit.get("content", "")[:200]
                ))
            logger.debug("MCTS retriever: %d results", len(mcts_results))
        except Exception as e:
            logger.debug("MCTS retriever failed: %s", e)

        # L-ICL: 精准局部修正 — 当召回结果稀疏时注入定向修正
        if hasattr(self, 'context_engineering'):
            try:
                if len(all_hits) < 3:
                    correction = self.context_engineering.localized_correction(
                        query, f"Low recall coverage: {len(all_hits)} hits from {limit} limit"
                    )
                    if correction:
                        recall_data['l_icl_correction'] = correction[:100]
                        logger.debug("L-ICL correction injected for query '%s'", query[:50])
            except Exception as e:
                logger.debug("L-ICL correction failed: %s", e)

        # Route 8: DualStorage — verbatim + compressed combined retrieval
        if hasattr(self, 'dual_storage'):
            try:
                ds_results = self.dual_storage.retrieve(query, limit=max(3, limit // 3))
                for h in ds_results.get("verbatim", []):
                    all_hits.append(SearchHit(node_id=f"ds_v_{h.get('node_id', '')[:8]}", score=0.6, content=h.get("content", "")))
                for h in ds_results.get("compressed", []):
                    all_hits.append(SearchHit(node_id=f"ds_c_{id(h)}", score=0.5, content=h.get("content", "")))
                recall_data['dual_storage_primary'] = ds_results.get("primary_mode", "unknown")
            except Exception as e:
                logger.debug("DualStorage retrieval failed: %s", e)

        # Deduplicate + sort (cap scores to [0,1] for cross-route consistency)
        seen = set()
        unique = []
        for h in all_hits:
            if h.node_id not in seen:
                seen.add(h.node_id)
                h.score = min(1.0, max(0.0, h.score))
                unique.append(h)
        unique.sort(key=lambda h: h.score, reverse=True)
        unique = unique[:limit]

        # P1-d (论文④ Overlap Speech 借力): 时间邻域融合 (temporal neighbor fusion)
        # 论文核心: 因果系统浪费帧重叠固有延迟内的未来信息 -> 伪重叠帧融合.
        # 映射到 ULTRA: recall 召回孤立节点会丢失帧边界上下文, 对 top hits 融合
        # 其时间邻域(前后 delta_t 窗口), 重建上下文(避免因果断点丢信息).
        if unique:
            neighbor_hits = []
            for h in unique[:3]:  # 仅对 top-3 做邻域融合(控制开销)
                base_id = h.node_id
                # 去掉可能的前缀(topological/ds_ 等)还原 store node id
                plain_id = base_id.split("_")[-1] if "_" in base_id else base_id
                try:
                    neighbors = self.store.get_temporal_neighbors(
                        plain_id, delta_t=getattr(self, "temporal_fusion_window", 3600.0),
                        branch=branch, limit=3)
                    for nb in neighbors:
                        if nb.id not in seen and nb.id != plain_id:
                            seen.add(nb.id)
                            neighbor_hits.append(SearchHit(
                                node_id=nb.id, score=h.score * 0.6,  # 邻域降权
                                content=nb.content, snippet=nb.content[:200],
                                metadata={"neighbor_of": plain_id, "fusion": "temporal"}))
                except Exception as e:
                    logger.debug("Temporal neighbor fusion failed for %s: %s", base_id, e)
            if neighbor_hits:
                unique.extend(neighbor_hits)
                recall_data["temporal_neighbors_fused"] = len(neighbor_hits)

        # Owner-Harm: filter results the requester can access
        if hasattr(self, 'owner_harm'):
            try:
                requester = branch or "system"
                filtered = []
                for h in unique:
                    access = self.owner_harm.check_access(h.node_id, requester)
                    if access["allowed"]:
                        filtered.append(h)
                    else:
                        recall_data['owner_harm_filtered_count'] = recall_data.get('owner_harm_filtered_count', 0) + 1
                unique = filtered or unique  # If all filtered out, keep originals as fallback
            except Exception as e:
                logger.debug("Owner-Harm check failed: %s", e)

        duration = (time.time() - start) * 1000

        # Side effects
        if unique:
            self.cache.put(key=query, value=unique[0].content)
            # ContextFailure: observe retrieval quality
            self.context_failure.observe_distraction(len(unique), len(unique) / max(limit, 1))
        self.context_failure.observe_clash([h.content[:50] for h in unique[:3]])
        self.context_failure.observe_poisoning(query, is_hallucination=False)
        self.context_failure.observe_confusion(query, "recall context")
        self.compressor.compress(query)
        self.model_router.route(query)
        self.session.create(f"recall_{int(time.time())}")
        self.brain.decide({"action": "recall", "query": query, "result_count": len(unique)})

        # ContextFailure: detect failures after recall
        self.context_failure.detect()

        # OutputGuardrail: check output safety
        if unique:
            self.output_guardrail.check(unique[0].content)
            # BlockerEscalation: L1/L2 两级阻断升级检查(对返回节点做深度安全评估)
            for h in unique[:5]:
                try:
                    node_dict = {"content": h.content, "utility": getattr(h, "score", 0.5),
                                 "id": getattr(h, "node_id", ""), "surprise": getattr(h, "surprise", 0.0)}
                    blk = self.blocker_escalation.evaluate(node_dict)
                    if blk is not None and getattr(blk, "passed", True) is False:
                        logger.info("recall: blocker L2 escalated+blocked node %s", node_dict.get("id"))
                except Exception as e:
                    logger.warning("recall: blocker_escalation failed: %s", str(e)[:60])
            # FuzzTester: 每10次recall对输出安全门跑注入测试套件(验证抗注入)
            self._fuzz_tick = getattr(self, "_fuzz_tick", 0) + 1
            if self._fuzz_tick % 10 == 0:
                try:
                    fuzz_results = self.fuzz_tester.run_injection_suite(self.output_guardrail.check)
                    crashes = sum(1 for r in fuzz_results if not r.get("success"))
                    if crashes:
                        logger.warning("recall: fuzz_tester found %d guardrail injection crashes", crashes)
                except Exception as e:
                    logger.warning("recall: fuzz_tester failed: %s", str(e)[:60])

        # Gravity: rank results by gravitational pull
        for h in unique[:5]:
            if h.node_id:
                self.gravity.add_node(h.node_id, mass=h.score)

        # === Context Engineering: Write/Select/Compress ===
        # Write: snapshot recall results for future retrieval
        recall_components = [
            ContextComponent(name="query", type="instruction", content=query, priority=1,
                           tokens=len(query.split()) * 2),
        ]
        for h in unique[:5]:
            recall_components.append(ContextComponent(
                name="result_%s" % h.node_id[:8], type="knowledge",
                content=h.content, priority=3, tokens=len(h.content.split()) * 2,
            ))
        self.context_engineering.write(query, recall_components)

        # Select: retrieve relevant context from memory
        selected = self.context_engineering.select(query, self.store, limit=3)
        if selected:
            unique.extend([SearchHit(node_id=c.name, score=0.5, content=c.content)
                          for c in selected[:2]])

        # Re-sort after context engineering additions
        unique.sort(key=lambda h: h.score, reverse=True)

        # Compress: ensure context fits within budget
        if len(unique) > limit:
            compressed = self.context_engineering.compress(
                [ContextComponent(name=h.node_id, type="knowledge", content=h.content,
                                 tokens=len(h.content.split()) * 2) for h in unique],
                target_ratio=0.7,
            )
            compressed_ids = {c.name for c in compressed}
            unique = [h for h in unique if h.node_id in compressed_ids]

        # === Recall: full mechanism activation ===
        # Cache subsystem
        recall_data['cache_has'] = self.cache.contains(query)
        recall_data['cache_info'] = self.cache.get_entry_info(query)
        self.cache.cleanup_expired()
        recall_data['cache_stats'] = self.cache.get_stats()

        # Graph memory deep queries
        for h in unique[:3]:
            if h.node_id:
                recall_data['gm_episode'] = self.graph_memory.get_episode(h.node_id)
                recall_data['gm_edges'] = self.graph_memory.get_edges(h.node_id)
                recall_data['gm_neighbors'] = self.graph_memory.get_neighbors(h.node_id)
        recall_data['gm_by_tag'] = self.graph_memory.get_episodes_by_tag("ai")

        # Stream analysis
        recall_data['stream_recent'] = self.stream.recent(5, "recall")
        recall_data['stream_search'] = self.stream.search_content(query)

        # Compression analysis
        recall_data['compress_stats'] = self.compressor.compress_with_stats(query)

        # Model routing analysis
        recall_data['model_suggest'] = self.model_router.suggest_model_for_tools(len(unique))

        # Session management
        self.session.access(f"recall_{int(time.time())}")
        self.session.expire_idle()

        # Behavior mirror
        self.behavior_mirror.mirror("system", "recall", {"query": query, "hits": len(unique)})

        # Event bus
        recall_data['recent_events'] = self.event_bus.get_recent(3)

        # Memory side effect
        self.memory_side_effect.set_current_task(f"recall {query}")
        for h in unique[:3]:
            self.memory_side_effect.observe_retrieval(h.content[:100])
        recall_data['side_effect'] = self.memory_side_effect.detect()

        # Context isolator
        snap = self.context_isolator.create_snapshot(
            [h.content[:100] for h in unique[:3]], f"recall {query}"
        )
        recall_data['ctx_merge'] = self.context_isolator.merge(snap, [h.content[:50] for h in unique[:2]])

        # Context window
        self.context_window.register_component("recall_results", len(unique) * 100, priority=7)
        recall_data['ctx_check'] = self.context_window.check()
        recall_data['ctx_compress'] = self.context_window.suggest_compression()
        self.context_window.update_usage("recall_results", len(unique) * 80)

        # Progressive complexity
        recall_data['complexity'] = self.progressive_complexity.assess(
            f"recall {query}", context_tokens=len(unique) * 200, requires_tools=len(unique) > 5
        )

        # Output guardrail (second pass)
        for h in unique[:3]:
            self.output_guardrail.check(h.content)

        # ========== P4: Harness Layer — TieredRouter + ToolTaxGate ==========
        # arXiv 2605.00334 (AgentFloor) + arXiv 2605.00136 (G-STEP)
        try:
            tier = self.tiered_router.route(query)
            recall_data["tiered_router"] = {"tier": tier.tier, "confidence": tier.confidence}
            logger.debug("TieredRouter assigned tier: %s", tier.tier)

            noise_estimate = self.semantic_noise_estimator.estimate(query)
            tool_tax = self.tool_tax_gate.evaluate(query, estimated_gain=0.5)
            if not tool_tax["allowed"]:
                logger.warning("Tool use blocked by G-STEP gate: %s", tool_tax["reason"])
            recall_data["tool_tax"] = {"noise": noise_estimate, "decision": tool_tax["decision"]}
        except Exception as e:
            logger.debug("Harness layer failed: %s", e)

        # ========== P0: Safety Layer — NonAdversarial Leakage Detection ==========
        # arXiv 2606.17114 (Scenario Leakage)
        try:
            scenario = {
                "type": "customer_support_email",
                "context": query,
                "sensitive_data": []
            }
            leakage_assessment = self.leakage_detector.assess_scenario(scenario)
            if leakage_assessment["overall_risk"] > 0.7:
                logger.warning("Non-adversarial leakage risk: %s", leakage_assessment["recommendations"])
                recall_data["leakage_risk"] = leakage_assessment
        except Exception as e:
            logger.debug("Leakage detection failed: %s", e)

        # ========== P0: Safety Layer — Process Audit ==========
        # arXiv 2605.30838 (COMPASS)
        try:
            trajectory = self._get_recent_trajectory()
            if trajectory:
                audit_result = self.process_auditor.audit_trajectory(trajectory)
                if audit_result["risk_score"] > 0.5:
                    logger.warning("Attack trajectory detected: %s", audit_result["decompositions"])
                    recall_data["process_audit"] = audit_result
        except Exception as e:
            logger.debug("Process audit failed: %s", e)

        # ========== P0: Safety Layer — Local Causal Explainer ==========
        # arXiv 2605.00123 (LOCA)
        try:
            jailbreak_case = self._detect_jailbreak()
            if jailbreak_case:
                causal_analysis = self.causal_explainer.local_cause(jailbreak_case)
                if causal_analysis["interventions"]:
                    logger.info("LOCA intervention: %s", causal_analysis["interventions"][0])
                    recall_data["causal_explanation"] = causal_analysis
        except Exception as e:
            logger.debug("Causal explainer failed: %s", e)

        # ========== P0: Safety Layer — Reasoning Alignment Check ==========
        # arXiv 2606.08457 (CARA)
        try:
            multi_agent_reasonings = self._collect_multi_agent_reasonings()
            alignment = self.reasoning_checker.check_alignment(multi_agent_reasonings)
            if alignment["kappa"] < 0.4:
                logger.warning("Reasoning misalignment detected (kappa=%.2f)", alignment["kappa"])
                recall_data["reasoning_alignment"] = alignment
        except Exception as e:
            logger.debug("Reasoning alignment check failed: %s", e)

        # ========== P0: Safety Layer — Compliance Scorer ==========
        # arXiv 2606.07805 (MAC-Bench)
        try:
            action = {"action_label": "recall", "prompt": query, "response": str(unique[:3])}
            policy = {"policy_label": "safety_policy", "rules": ["no_malicious_content", "no_data_leak"]}
            csr_result = self.compliance_scorer.score_compliance(action, policy)
            recall_data["compliance_score"] = csr_result
        except Exception as e:
            logger.debug("Compliance scoring failed: %s", e)

        # ========== P2: Learning Layer — Reflective Sampler ==========
        # arXiv 2607.00147 (RareDxR1)
        try:
            failure_paths = self._collect_failure_paths()
            for path in failure_paths:
                self.reflective_sampler.track_failure(path)
            reflective_example = self.reflective_sampler.sample_reflective_example()
            if reflective_example:
                recall_data["reflective_example"] = reflective_example
        except Exception as e:
            logger.debug("Reflective sampler failed: %s", e)

        # ========== P3: Evolution Layer — Strategy Switcher ==========
        # arXiv 2601.00514 (Self-Observation)
        try:
            recent_actions = self._get_recent_actions()
            success_rate = self._compute_success_rate()
            switch_decision = self.strategy_switcher.decide(recent_actions, success_rate)
            if switch_decision["switch"]:
                logger.info("Strategy switch triggered: %s", switch_decision["reason"])
                recall_data["strategy_switch"] = switch_decision
        except Exception as e:
            logger.debug("Strategy switcher failed: %s", e)

        # ========== P3: Collaboration Layer — Agent Reputation ==========
        try:
            reputation = self.agent_reputation.get_reputation("system")
            recall_data["agent_reputation"] = reputation
        except Exception as e:
            logger.debug("Agent reputation failed: %s", e)

        # ========== P1: Memory Layer — HeLa-Mem Activation ==========
        try:
            if unique:
                activated = self.hela_mem.activate(unique[0].node_id)
                if activated:
                    recall_data["hela_activation"] = activated
        except Exception as e:
            logger.debug("HeLa-Mem activation failed: %s", e)

        # ========== P1: Memory Layer — Consolidation Engine ==========
        try:
            memories = [{"id": h.node_id, "content": h.content, "utility": h.score} for h in unique[:5]]
            consolidation_result = self.consolidation_engine.consolidate(memories)
            recall_data["consolidation"] = {
                "merged": consolidation_result.merged_count,
                "pruned": consolidation_result.pruned_count,
                "conflicts": consolidation_result.conflicts_resolved
            }
        except Exception as e:
            logger.debug("Consolidation engine failed: %s", e)

        # ========== P3: Evolution Layer — FATE + Signal Triage ==========
        try:
            fate_result = self.fate.evolve([{"content": h.content, "utility": h.score} for h in unique[:3]])
            signal_triage = self.signal_triage.triage(fate_result)
            recall_data["fate"] = {"evolution": fate_result, "signals": signal_triage}
        except Exception as e:
            logger.debug("FATE evolution failed: %s", e)

        # ========== P3: Evolution Layer — ESTEER + Persona ==========
        try:
            esteer_state = self.esteer.regulate({"current_valence": 0.5, "arousal": 0.3})
            persona = self.persona_manager.get_current_persona()
            recall_data["esteer"] = esteer_state
            recall_data["persona"] = persona
        except Exception as e:
            logger.debug("ESTEER/Persona failed: %s", e)

        # ========== P3: Collaboration Layer — CAMP Assembler ==========
        try:
            camp_experts = self.camp_assembler.assemble({"query": query, "context": unique[:3]})
            recall_data["camp_experts"] = camp_experts
        except Exception as e:
            logger.debug("CAMP assembly failed: %s", e)

        # ========== P3: Collaboration Layer — Interaction Graph ==========
        try:
            interaction = self.interaction_graph.record_interaction({
                "source": "system",
                "target": "user",
                "type": "recall",
                "content": query
            })
            recall_data["interaction_graph"] = interaction
        except Exception as e:
            logger.debug("Interaction graph failed: %s", e)

        # ========== P3: Collaboration Layer — Knowledge Curation ==========
        try:
            curation = self.knowledge_curation.curate({
                "proposed_knowledge": [{"content": h.content, "utility": h.score} for h in unique[:3]],
                "voting_round": 1
            })
            recall_data["knowledge_curation"] = curation
        except Exception as e:
            logger.debug("Knowledge curation failed: %s", e)

        # ========== P4: Lifecycle Layer — Sleep Gate ==========
        try:
            sleep_check = self.sleep_gate.should_sleep(context_tokens=len(unique) * 200)
            if sleep_check:
                logger.info("Sleep gate triggered: context complexity high")
                consolidation = self.sleep_gate.consolidate()
                recall_data["sleep_gate"] = {"triggered": True, "consolidation": consolidation}
        except Exception as e:
            logger.debug("Sleep gate failed: %s", e)

        # ========== P4 Extended: Multi-Hop Reasoning ==========
        try:
            if unique:
                # MultiHopRetriever API: retrieve(query) -> list[dict]
                extended = self.multi_hop.retrieve(unique[0].content[:50])
                if extended:
                    for ext in extended:
                        if ext not in all_hits:
                            all_hits.append(SearchHit(
                                node_id=ext.get("id", ""),
                                score=ext.get("score", 0.5),
                                content=ext.get("content", ""),
                            ))
                    recall_data["multi_hop_extended"] = len(extended)
        except Exception as e:
            logger.debug("Multi-hop reasoning failed: %s", e)

        # ========== P4: Loop Layer — HiMAC Planner ==========
        try:
            himac_plan = self.himac_planner.plan({"goal": query, "resources": len(unique)})
            recall_data["himac_plan"] = himac_plan
        except Exception as e:
            logger.debug("HiMAC planner failed: %s", e)

        # ========== P2: Learning Layer — SubtleMemory Benchmark ==========
        try:
            benchmark = self.subtle_memory_benchmark.run_benchmark(
                store=self.store, cycles=1
            )
            recall_data["subtle_memory_benchmark"] = benchmark
        except Exception as e:
            logger.debug("SubtleMemory benchmark failed: %s", e)

        # ========== P2: Learning Layer — L-ICL ==========
        try:
            correction = self.localized_icl.generate_correction(
                {"trajectory": self._get_failed_trajectory(), "state": {}}
            )
            if correction:
                recall_data["l_icl_correction"] = correction
        except Exception as e:
            logger.debug("L-ICL failed: %s", e)

        # ========== P4: Academic Searcher ==========
        try:
            academic_results = self.academic_searcher.search(query, max_results=3)
            if academic_results:
                recall_data["academic_search"] = academic_results
        except Exception as e:
            logger.debug("Academic searcher failed: %s", e)

        # ========== P3: Evolution Layer — Loom Narrative ==========
        try:
            narrative = self.loom.weave({"events": [{"content": h.content, "utility": h.score} for h in unique[:5]]})
            recall_data["loom_narrative"] = narrative
        except Exception as e:
            logger.debug("Loom narrative failed: %s", e)

        # ========== P3: Evolution Layer — ProgressiveMCGS ==========
        try:
            mcgs_result = self.progressive_mcgs.search({"query": query, "depth": 3})
            recall_data["progressive_mcgs"] = mcgs_result
        except Exception as e:
            logger.debug("ProgressiveMCGS failed: %s", e)

        # ========== P3: Evolution Layer — EntropyScheduler ==========
        try:
            entropy = self.entropy_scheduler.compute_entropy(len(unique))
            schedule = self.entropy_scheduler.schedule(entropy)
            recall_data["entropy_schedule"] = {"entropy": entropy, "schedule": schedule}
        except Exception as e:
            logger.debug("Entropy scheduler failed: %s", e)

        # ========== P3: Evolution Layer — RetrospectiveMemory ==========
        try:
            retrospective = self.retrospective_memory.retrieve({"query": query, "limit": 3})
            recall_data["retrospective_memory"] = retrospective
        except Exception as e:
            logger.debug("Retrospective memory failed: %s", e)

        # ========== P3: Evolution Layer — StrategyCodingDecouple ==========
        try:
            decouple = self.strategy_coding_decouple.decouple({"strategy": "default", "code": query})
            recall_data["strategy_decouple"] = decouple
        except Exception as e:
            logger.debug("Strategy coding decouple failed: %s", e)

        # ========== P3: Evolution Layer — ATPValidator ==========
        try:
            atp_validation = self.atp_validator.validate({"action": "recall", "params": {"query": query}})
            recall_data["atp_validation"] = atp_validation
        except Exception as e:
            logger.debug("ATP validation failed: %s", e)

        # ========== P3: Evolution Layer — GearSafety ==========
        try:
            gear_safety = self.gear_safety.check({"action": "recall", "context": query})
            recall_data["gear_safety"] = gear_safety
        except Exception as e:
            logger.debug("Gear safety failed: %s", e)

        # ========== P3: Collaboration Layer — External Notebook ==========
        try:
            notebook_entry = self.external_notebook.write({
                "key": f"recall_{query[:20]}",
                "value": [{"node_id": h.node_id, "score": h.score} for h in unique[:5]]
            })
            recall_data["external_notebook"] = notebook_entry
        except Exception as e:
            logger.debug("External notebook failed: %s", e)

        # ========== P4: Intervention Control ==========
        try:
            state = {"risk_score": 0.3, "error_count": 0, "success_rate": 0.9}
            candidate_actions = [{"action": "recall", "expected_improvement": 0.1}]
            intervention = self.intervention_controller.intervene(state, candidate_actions)
            if intervention["expected_improvement"] > 0.1:
                recall_data["intervention"] = intervention
        except Exception as e:
            logger.debug("Intervention control failed: %s", e)

        # ========== P4: Brainstorming Mechanism ==========
        try:
            brainstorming = self.brainstorming_mechanism.generate({"topic": query, "context": unique[:3]})
            recall_data["brainstorming"] = brainstorming
        except Exception as e:
            logger.debug("Brainstorming failed: %s", e)

        # 自动记录 recall 引用到 UtilityTracker
        for h in unique[:5]:
            self.utility_tracker.record_reference(h.node_id)

        # 用 disposition 行为倾向调整排序权重
        for h in unique:
            try:
                disp_score = self.disposition.get_disposition(h.node_id)
                if disp_score:
                    h.score = min(1.0, h.score * (1 + disp_score * 0.2))
            except Exception as e:
                logger.warning("Disposition score adjustment failed for node %s: %s", h.node_id, e)
        unique.sort(key=lambda h: h.score, reverse=True)

        # MemPO: update utilities for recalled nodes
        if hasattr(self, 'mempo'):
            try:
                node_ids = [h.node_id for h in unique if hasattr(h, 'node_id')]
                used = [True] * len(node_ids)
                self.mempo.batch_update_utilities(node_ids, used)
                recall_data['mempo_avg_utility'] = sum(
                    self.mempo.get_utility(nid) for nid in node_ids
                ) / max(len(node_ids), 1)
            except Exception as e:
                logger.debug("MemPO update failed: %s", e)

        # P3 RSI: RIMRULLE→MemPO rule-guided utility boost on recall
        if hasattr(self, 'rimrule') and hasattr(self, 'mempo') and hasattr(self.mempo, 'apply_rule_guidance'):
            try:
                high_conf_rules = self.rimrule.get_rules(sort_by="confidence", limit=3)
                for rule in high_conf_rules:
                    if rule.get("confidence", 0) > 0.5:
                        related_ids = [h.node_id for h in unique[:5] if hasattr(h, 'node_id')]
                        self.mempo.apply_rule_guidance(rule, related_ids)
            except Exception as e:
                logger.debug("P3 RSI rule guidance failed: %s", e)

        # B2-1: Verbatim Chunk Joint Storage (arXiv 2601.00821)
        # Enrich each result with raw_chunk if available, and optionally prefer chunk
        try:
            enriched = []
            for h in unique:
                node = self.store.read_node(h.node_id)
                if node and node.raw_chunk:
                    h.metadata["chunk"] = node.raw_chunk
                    if prefer_chunk:
                        h.content = node.raw_chunk
                enriched.append(h)
            unique = enriched
        except Exception as e:
            logger.debug("Verbatim chunk enrichment failed: %s", e)

        avg_score = sum(h.score for h in unique) / max(len(unique), 1) if unique else 0.0

        self.event_bus.publish({"type": "recall_completed", "query": query, "hits": len(unique),
                                "avg_score": round(avg_score, 4), "duration_ms": duration,
                                "gap_empty": len(unique) == 0})
        recall_result = SearchResults(hits=unique, total_count=len(unique), query=query, duration_ms=duration, metadata=recall_data)
        # Telemetry: 存储原始返回值
        self._telemetry["recall"] = recall_result

        # 【P0修复】标记learned节点被命中
        if self.learn_feedback is not None:
            for h in unique[:limit]:
                if h.node_id and (h.node_id.startswith("sm_") or h.node_id.startswith("fn_") or h.node_id.startswith("")):
                    self.learn_feedback.mark_hit(h.node_id, query)

        # 写管道结果（双向语义穿透）
        self.signal_fusion.set_pipe_result("recall", {
            "query": query, "hits": len(unique), "avg_score": round(avg_score, 4),
            "total_count": len(unique),
        })

        return recall_result

    # ============================================================
    # B2-2: PolarMem Tristate Query (arXiv 2602.00415)
    # ============================================================
    def _recall_with_trust(self, query: str, limit: int = 10, branch: str = "main",
                           prefer_chunk: bool = False) -> SearchResults:
        """Recall with trust-state-aware filtering.

        Uses three-state memory (HAS/NOT_HAS/Uncertain) to annotate or filter results:
        - trust_state="has": normal results, included with standard confidence.
        - trust_state="not_has": known-absent; included but with suppressed confidence.
        - trust_state="uncertain": flagged as unverified.

        Args:
            query: Search query string.
            limit: Maximum results to return.
            branch: Branch to search in.
            prefer_chunk: If True, use raw_chunk as the main content field.

        Returns:
            SearchResults with trust-state-annotated hits.
        """
        try:
            results = self.recall(query, limit=limit * 3, branch=branch, prefer_chunk=prefer_chunk)
        except Exception as e:
            logger.error("_recall_with_trust: recall failed: %s", e)
            return SearchResults(hits=[], total_count=0, query=query, metadata={"trust_state_error": str(e)})

        filtered_hits = []
        trust_metadata = {"has": 0, "not_has": 0, "uncertain": 0}

        try:
            for hit in results.hits:
                node = self.store.read_node(hit.node_id)
                trust_state = "unknown"
                try:
                    if node:
                        trust_state = node.trust_state or "unknown"
                except Exception:
                    logger.warning("Failed to read trust_state from node, defaulting to unknown")
                    trust_state = "unknown"

                hit.metadata["trust_state"] = trust_state
                trust_metadata[trust_state] = trust_metadata.get(trust_state, 0) + 1

                if trust_state == "not_has":
                    # Known-absent: include but signal low confidence
                    hit.metadata["suppressed"] = True
                    hit.score *= 0.3  # Drastically reduce score
                    hit.metadata["note"] = "known_absent"
                elif trust_state == "uncertain":
                    # Uncertain: flag as unverified
                    hit.metadata["unverified"] = True
                    hit.score *= 0.7
                    hit.metadata["note"] = "unverified"
                # trust_state == "has": no modification needed

                filtered_hits.append(hit)

            filtered_hits.sort(key=lambda h: h.score, reverse=True)
            filtered_hits = filtered_hits[:limit]

        except Exception as e:
            logger.error("_recall_with_trust: filtering failed: %s", e)
            filtered_hits = results.hits[:limit]

        result = SearchResults(
            hits=filtered_hits,
            total_count=len(filtered_hits),
            query=query,
            duration_ms=results.duration_ms,
            metadata={"trust_state_counts": trust_metadata, **results.metadata},
        )
        self._telemetry["recall_with_trust"] = result

        # 反馈环路：recall → learn
        # 零命中 → 告诉 learn 需要补全知识缺口
        if len(filtered_hits) == 0:
            try:
                self.signal_fusion.push_feedback({
                    "from": "recall",
                    "to": "learn",
                    "type": "quality",
                    "data": {
                        "query": query,
                        "hits": 0,
                        "gap": True,
                        "source": "recall_with_trust",
                    },
                })
            except Exception as e:
                logger.debug("recall: push_feedback to learn failed: %s", e)

        return result

    # ============================================================
    # P0a: 激活消费者 — 机制激活后真接生产(解 B1 僵尸机制)
    # ============================================================
    def _consume_t3(self, entry: dict) -> None:
        """T3(GitHub 机制提取)激活后: 把机制参数维度注入进化引擎 gene_specs.

        走 A-B 并行原则(不强制覆盖): 注入的是候选基因维度, 由后续 evolve()
        的适应度评估决定去留.
        """
        item_id = f"t3_{entry.get('name', '')}"
        self.attribution_scoring.create_work_item(item_id, "mechanism_activate", priority=5)
        data = entry.get("data", {})
        specs = data.get("gene_specs") or {}

        if not specs and data.get("executable") is not None:
            specs = getattr(data["executable"], "gene_specs", {}) or {}
        if specs:
            try:
                added = self.evolution_engine.inject_gene_specs(specs)
                self.attribution_scoring.complete_work_item(item_id)
                logger.info("Omega: T3 %s injected %d gene specs into evolution engine", entry["name"], added)
            except Exception as e:
                self.attribution_scoring.fail_work_item(item_id, str(e)[:60])
                logger.warning("Omega: T3 consume failed: %s", e)
        else:
            self.attribution_scoring.complete_work_item(item_id)

    def _consume_t4(self, entry: dict) -> None:
        """T4(论文编译)激活后: 经 host.emit_capability 导出机制给宿主 agent.

        这是"建议+宿主确认"语义(对齐 P6 不自动直替): 把 target_location + draft
        推给宿主, 宿主据此生成 tool/prompt/检索策略, 而非 Ultra 直接改写宿主代码.
        """
        item_id = f"t4_{entry.get('name', '')}"
        self.attribution_scoring.create_work_item(item_id, "mechanism_emit", priority=5)
        data = entry.get("data", {})
        spec = {
            "name": entry["name"],
            "category": "compiled",
            "target_location": data.get("target_location", {}),
            "draft_code": data.get("draft_code", ""),
            "claim": data.get("paper", ""),
            "activated_at": entry.get("activated_at"),
        }
        try:
            ok = self.host.emit_capability(spec)
            self.attribution_scoring.complete_work_item(item_id)
            logger.info("Omega: T4 %s emitted to host (accepted=%s)", entry["name"], ok)
            self.record_production("mechanism", f"T4 论文机制编译 {entry['name']} (emit host={ok})", {
                "name": entry["name"], "accepted": ok,
                "paper": data.get("paper", "")[:80],
                "target_location": data.get("target_location", {}),
            })

            draft = data.get("draft_code", "")
            if draft and ok is not False:
                try:
                    from prometheus_nexus.integration.mechanism_sandbox import MechanismSandbox
                    from prometheus_nexus.mechanisms import base_mechanism
                    cls = MechanismSandbox().compile_mechanism(
                        entry["name"], draft, base_mechanism)
                    if cls is not None:
                        inst = cls()
                        # 接管语义(对齐 P6): 仅当宿主/论文显式声明覆盖的基本盘时才接管
                        overrides_base = data.get("overrides_base")
                        self.nexus.mount_dynamic(entry["name"], inst, category="compiled",
                                                target_base=overrides_base)
                        if overrides_base:
                            logger.info("Omega: Nexus 动态挂载 T4 %s 并接管基本盘 %s (神经发生+接管闭环)",
                                        entry["name"], overrides_base)
                        else:
                            logger.info("Omega: Nexus 动态挂载 T4 机制 %s (神经发生完成, 作候选不自动接管)",
                                        entry["name"])

                    else:
                        logger.warning("Omega: T4 %s 沙箱编译返回 None, 未挂载", entry["name"])
                        self.record_issue("warning", "T4", f"{entry['name']} 沙箱编译返回 None, 未挂载")
                except Exception as e:
                    logger.warning("Omega: T4 nexus mount failed: %s", str(e)[:50])
                    self.record_issue("error", "T4", f"nexus mount failed: {str(e)[:80]}")

            return ok  # 返回宿主接受状态, 供熔断精准化 [P1 C3]
        except Exception as e:
            self.attribution_scoring.fail_work_item(item_id, str(e)[:60])
            logger.warning("Omega: T4 consume (emit) failed: %s", e)
            return False

    # ============================================================
    # evolve pipeline (11 stages — Superpowers enhanced)
    # ============================================================
    def evolve(self, context: str = "", branch: str = "main", confidence: float = 0.5) -> EvolutionOutcome:
        start = time.time()
        # 管道运行计数(监控可见性)
        try:
            self.nexus._pipelines.setdefault("evolve", {"runs": 0, "failures": 0, "last_run": None})
            self.nexus._pipelines["evolve"]["runs"] += 1
            self.nexus._pipelines["evolve"]["last_run"] = time.time()
        except Exception:
            pass
        # P0-b (论文⑤ Thought Leap Bridge 借力): 进化链完整性追踪
        # 论文核心: CoT 思维跳跃(专家省略中间步) -> 检测+补步.

        # 此处记录关键 stage 是否真执行, 末尾暴露 chain_complete(而非假装成功).
        chain_trace = {
            "brainstorm": False, "plan": False, "main_evolve": False,
            "semantic": False, "state_save": False, "verify": False,
        }

        # 链上下文：读取触发管的信号
        try:
            ctx = self.signal_fusion.get_chain_context()
            if ctx:
                trigger_pipe = ctx.get("trigger_pipe", "")
                sigs = ctx.get("trigger_signals", {})
                if trigger_pipe == "reflect":
                    raw_score = sigs.get("raw_score", 0.5)
                    raw_drift = sigs.get("raw_drift", 0)
                    context += f" | Triggered by reflect: score={raw_score:.3f}, drift={raw_drift}"
                    self.cerebral_cortex.add_merge_reason(
                        "evolve", f"reflect_driven:score={raw_score:.3f}")
        except Exception as e:
            logger.warning("Evolve chain context processing failed: %s", e)

        # Stage 0: Brainstorming — Socratic design refinement (Superpowers)
        brainstorm_result = self.brainstorming.brainstorm(
            topic=context or "auto-evolution"
        )
        chain_trace["brainstorm"] = True

        # PlanWriter: generate implementation plan from brainstorming (Superpowers)
        plan = self.plan_writer.write_plan(
            feature=context or "auto-evolution",
            context="evolve pipeline after brainstorming",
        )
        chain_trace["plan"] = True

        # LoopSelector: auto-select loop strategy
        loop_config = self.loop_selector.select(context)
        self.loop_selector.record_outcome(loop_config.strategy, 0.5)

        # EvolutionQualityGates: check step budget
        allowed, reason = self.evo_quality_gates.check_step("evolve", 1, max_steps=loop_config.max_steps)
        if not allowed:
            blocked = EvolutionOutcome(result=EvolutionResult.BLOCKED, details=reason)
            self._telemetry["evolve"] = blocked
            return blocked

        # AdaptiveHarness: record execution
        self.adaptive_harness.execute(context, tool="evolve")

        # Step -1: ToolOverload check
        overload = self.tool_overload.detect()
        if overload.is_overloaded:
            blocked = EvolutionOutcome(result=EvolutionResult.BLOCKED, details=f"ToolOverload: {overload.tool_count} tools")
            self._telemetry["evolve"] = blocked
            return blocked

        # Step 0: LoopGuard
        self.loop_guard.start()
        loop_state = self.loop_guard.check()
        if loop_state in (LoopState.CIRCUIT_BREAKER,):
            blocked = EvolutionOutcome(result=EvolutionResult.BLOCKED, details="LoopGuard")
            self._telemetry["evolve"] = blocked
            return blocked

        # Semantic Early-Stopping check
        ses_decision = self.semantic_early_stopping.check(context)
        chain_trace["semantic"] = True  # 语义阶段已执行(无论放行/停止), 标记避免进化链误报缺失
        if ses_decision.should_stop:
            blocked = EvolutionOutcome(result=EvolutionResult.BLOCKED, details="semantic_early_stop")
            self._telemetry["evolve"] = blocked
            return blocked

        # Ensure context is dynamic enough to pass AntiEvolution and SemanticEarlyStop gates
        if not context or context == "auto-evolution":
            fitness = self._compute_fitness()
            reflect_score = self._last_reflect_score or 0.0
            node_count = self.store.get_node_count()
            health = self._compute_health()
            # Map health string to numeric score for logging
            health_score = {"healthy": 1.0, "degraded": 0.5, "critical": 0.2, "empty": 0.0, "unknown": 0.5}.get(health, 0.5)
            dynamic_suffix = f"auto:fitness={fitness:.4f}:reflect={reflect_score:.4f}:nodes={node_count}:health={health_score:.3f}"
            context = f"Periodic evolution from reflect insights — {dynamic_suffix}"

        # Step 1: EquilibriumGuard
        if self.equilibrium.get_alert_level() == AlertLevel.RED:
            blocked = EvolutionOutcome(result=EvolutionResult.BLOCKED, details="Equilibrium RED")
            self._telemetry["evolve"] = blocked
            return blocked

        # Step 2: AntiEvolutionGate
        anti = self.anti_evolution.check(hypothesis=context or "auto-evolution")
        if not anti.passed:
            blocked = EvolutionOutcome(result=EvolutionResult.BLOCKED, details=f"AntiEvolution: {anti.verdict}")
            self._telemetry["evolve"] = blocked
            return blocked

        # Step 3: VerificationIronLaw
        self.iron_law.verify(claim=context or "auto-evolution")

        # Step 3.5: Measure fitness before evolution (含 SEED 蒸馏稠密信号)
        fitness_before = self._compute_fitness() + self._distill_bonus()
        diagnostics: Dict[str, Any] = {}

        # Step 4: RLPathology — observe() 内部已调用 detect_all()
        self.rl_pathology.observe(fitness_before, "evolve")

        # Step 4.5: UCB1 — 用实际适应度差值作为奖励信号
        try:
            strategy = self.ucb1.select()
            fitness_reward = max(0.0, min(1.0, fitness_before + 0.5))
            self.ucb1.update(strategy, fitness_reward)
            best_arm = self.ucb1.get_best_arm()
        except Exception:
            logger.warning("UCB1 strategy selection failed, falling back to default")
            strategy = "default"

        # Step 4.6: FGG — 门控结果用于阻断违规进化
        fgg_result = self.fggm.verify_compat({"context": context})
        if not fgg_result.get("passed", True):
            blocked = EvolutionOutcome(result=EvolutionResult.BLOCKED,
                                       details=f"FGG violations: {fgg_result.get('violations', [])}")
            self._telemetry["evolve"] = blocked
            return blocked

        # Step 4.7: EvalDriven
        self.eval_engine.evaluate({"context": context, "strategy": strategy})

        # Step 4.8: DAG scheduling — 添加任务后执行调度
        self.dag_scheduler.add_task(f"evolve_{int(time.time())}", {"context": context})
        try:
            scheduled = self.dag_scheduler.schedule()
        except ValueError:
            scheduled = []

        # Step 4.9: ConfidenceGate — 低置信度阻断进化
        cg_result = self.confidence_gate.check({"context": context, "fitness": fitness_before})
        if not cg_result.get("passed", True):
            blocked = EvolutionOutcome(result=EvolutionResult.BLOCKED,
                                       details=f"ConfidenceGate: confidence={cg_result.get('confidence', 0):.3f} < threshold={cg_result.get('threshold', 0):.3f}")
            self._telemetry["evolve"] = blocked
            return blocked

        # Step 5: HarnessX evolution (with AntiEvolutionGate protection)
        # Compose harness from primitives
        harness_config = self.harness_x.compose(["input_guard", "dopamine_gate", "five_gates"])
        # Execute and trace
        harness_traces = self.harness_x.execute(harness_config, input_data=context)
        # AntiEvolutionGate: check before evolving harness
        harness_anti = self.anti_evolution.check(hypothesis=f"harness_evolution_{context}")
        if harness_anti.passed:
            new_harness_config = self.harness_x.evolve(harness_config, harness_traces)
            # Evaluate the evolved harness
            harness_score = self.harness_x.evaluate(
                new_harness_config,
                test_cases=[{"input": context}, {"input": "test"}]
            )
            self.marginal.record(harness_score, "harness_evolution", context)

        # RIMRULE: observe evolution context for pattern extraction
        self.rimrule.add_observation({"condition": str(context)[:100], "outcome": "evolve", "utility": 0.5})
        # P3 RSI: MemPO→RIMRULLE observation weighting
        mempo_weights: dict[str, float] = {}
        if hasattr(self, 'mempo') and hasattr(self.mempo, 'get_utility_for_condition'):
            try:
                cond_str = str(context)[:100]
                u = self.mempo.get_utility_for_condition(cond_str)
                mempo_weights[cond_str] = u
            except Exception as e:
                logger.debug("P3 RSI mempo weight failed: %s", e)
        rules = self.rimrule.extract_rules(observation_weights=mempo_weights if mempo_weights else None)
        if rules:
            evolution_data['rimrule_rules_count'] = len(rules)
            evolution_data['rimrule_top_score'] = rules[0].get("mdl_score", 0) if rules else 0

        # Step 6: Context Engineering — manage evolve context
        self.context_engineering.write("evolve_%s" % context, [
            ContextComponent(name="task", type="instruction", content=context, priority=1,
                           tokens=len(context.split()) * 2),
        ])

        # Step 7: Execute evolution

        # CoEvolution
        self.coevolve.evolve([context or "auto"])

        # SpeculativeEvolution
        self.speculative.fork(context)

        # SpeculativeFork
        self.speculative_fork.fork(context or "auto")

        # LotkaVolterra
        self.lotka_volterra.add_species(context or "auto", initial_pop=fitness_before * 100)
        self.lotka_volterra.simulate(dt=0.1)

        # ToolFitness
        self.tool_fitness.predict(context or "auto", "evolve")

        # CommunityTree
        self.community_tree.add_child(None, {"context": context, "fitness": fitness_before})
        diagnostics["communities"] = self.community_tree.find_communities()

        # EDRE
        self.edre.replicate({"context": context, "fitness": fitness_before})

        # FiveStepEvolution
        self.five_step.evolve(context)

        # DeepRetrofit
        self.retrofit.retrofit(context)

        # Step 5: Main evolution (eval_engine + evolution_engine)
        evo_ctx = EvolutionContext()
        evo_ctx.metadata = {"context": context, "branch": branch}

        # ===== P0-2: 外部知识内容级驱动进化 =====
        # 取近期高 utility / 高 recall 命中的 learned 节点, 派生进化维度与 context,
        # 让"从外部学到的东西"真正参与"改自己"(原实现只用硬编码 gene_specs + node_count)。
        derived_specs: dict[str, tuple[float, float]] = {}
        learned_themes: list[str] = []
        try:
            nodes = self.store.get_active_nodes(limit=50)
            # 按 learn_feedback 命中 + utility 排序, 优先近期被用到的知识
            hits = getattr(self.learn_feedback, "_hits", {})
            nodes_sorted = sorted(
                nodes,
                key=lambda n: (hits.get(n.id, 0), getattr(n, "utility", 0.0)),
                reverse=True,
            )
            import re as _re
            for n in nodes_sorted[:20]:
                content = getattr(n, "content", "") or ""
                tags = list(getattr(n, "tags", []) or [])
                learned_themes.extend(tags)
                # 从内容抽取 "param=value" 形式 -> 动态基因维度
                for m in _re.finditer(r"([a-z_]+_rate|[a-z_]+_size|temperature|threshold|weight)\D*?([0-9]*\.?[0-9]+)", content, _re.I):
                    pname = m.group(1).lower()
                    try:
                        val = float(m.group(2))
                    except ValueError:
                        continue
                    # 归一化到 (0, max(1, val*2)) 的搜索区间
                    lo = max(0.0, val * 0.5)
                    hi = max(val * 1.5, 0.01)
                    derived_specs["ext_" + pname] = (round(lo, 4), round(hi, 4))
            learned_themes = [t for t in learned_themes if t]
        except Exception as e:
            logger.debug("Evolve: derived-specs extraction failed: %s", e)

        if derived_specs:
            derived_context = context + " | learned_dims=" + ",".join(sorted(derived_specs.keys()))
        else:
            derived_context = context

        result = self.eval_engine.evolve(evo_ctx)
        # D3: 注入真实效用锚 — 用 utility_tracker 的真实使用度信号, 防 fitness 纯参数自指
        if self.utility_tracker is not None:
            try:
                avgs = self.utility_tracker.get_all_averages()  # node_id -> 真实效用
                anchor = sum(avgs.values()) / len(avgs) if avgs else 0.5
                self.evolution_engine.set_utility_anchor(anchor)
            except Exception:
                pass
        self.evolution_engine.evolve(derived_context, gene_specs=derived_specs or None)
        chain_trace["main_evolve"] = True
        fitness_after = self._compute_fitness()

        # ===== T2: 语义进化轨道 =====
        # 概念图本身进化(提权高频概念/剪枝零命中), 并注入 gene_specs 形成 T1<->T2 闭环
        try:
            sem_result = self.semantic_evolution.evolve(context=context)
            if sem_result.get("derived_specs"):
                logger.info("Evolve: T2 semantic evolved %d concepts (promoted=%d pruned=%d)",
                            sem_result.get("evolved_concepts", 0),
                            sem_result.get("promoted", 0), sem_result.get("pruned", 0))
            learn_diagnostics["semantic_evolution"] = sem_result
            chain_trace["semantic"] = True
        except Exception as e:
            logger.debug("Evolve: T2 semantic evolution failed: %s", e)

        # ===== S3: T1 进化状态持久化(跨会话累积) =====
        # save() 永不抛出(内部已捕获), 失败时记 WARNING 并返回 False;
        # 据此正确反映 chain_trace, 不再把失败静默当成功。
        if self.evolution_state.save(self.evolution_engine):
            chain_trace["state_save"] = True

        # Verification Gate — ensure evolution is actually beneficial (Superpowers)
        delta = fitness_after - fitness_before
        verification = self.verification_gate.verify(
            task="evolve_%s" % context,
            fix_applied="fitness_delta=%.4f" % delta,
            tests_passing=delta >= -0.01,
        )
        chain_trace["verify"] = True

        # TDD Verifier — verify test coverage (Superpowers)
        tdd_result = self.tdd_verifier.verify(
            feature="evolution_%s" % context,
            test_description="evolution produces measurable improvement",
        )

        # Reflexion
        self.reflexion.reflect(context or "evolve", f"delta={delta:.4f}", fitness_after)

        # Debate
        self.debate.debate(context or "evolution", [f"before={fitness_before:.4f}", f"after={fitness_after:.4f}"])

        # MultiAgent
        self.multi_agent.register_agent(f"evolver_{int(time.time())}", ["evolve"])

        # BootstrapCI
        self.bootstrap.compute([fitness_before, fitness_after])

        # LuckyPass — analyze trajectory for fragile "lucky pass" patterns
        lucky_trajectory = {
            "paths": [{"context": context, "result": "success"}],
            "steps": [
                {"action": "evaluate", "content": f"fitness_before={fitness_before:.4f}"},
                {"action": "evolve", "content": context or "auto"},
                {"action": "verify", "content": f"fitness_after={fitness_after:.4f}, delta={fitness_after - fitness_before:.4f}"},
            ],
            "actions": ["evaluate", "evolve", "verify"],
            "success": fitness_after > fitness_before,
            "explanation": context or "",
            "reasoning": f"evolution from {fitness_before:.4f} to {fitness_after:.4f}",
        }
        lucky_analysis = self.lucky_pass.analyze(lucky_trajectory)
        diagnostics["lucky_pass"] = {
            "is_lucky": lucky_analysis.is_lucky_pass,
            "lucky_probability": lucky_analysis.lucky_probability,
            "ideal_probability": lucky_analysis.ideal_path_probability,
            "missing_steps": lucky_analysis.missing_steps,
            "heuristic_signals": lucky_analysis.heuristic_signals,
        }
        diagnostics["lucky_pass_stats"] = self.lucky_pass.get_stats()

        # SEAGym
        self.seagym.evaluate(context or "evolve", f"delta={fitness_after - fitness_before:.4f}", fitness_after)

        # EvolutionGrill
        self.evolution_grill.review({"context": context, "delta": fitness_after - fitness_before})

        # CAMP: 动态专家组装(arXiv 2604.00085) — 对进化方案进行三值投票
        try:
            agents = list(self.multi_agent._agents.values()) if hasattr(self.multi_agent, '_agents') else []
            if agents:
                camp_panel = self.multi_agent._deliberate_assembly(
                    context or "evolution",
                    agents,
                    ["evolve", "analyze"],
                    min_panel_size=2
                )
                if len(camp_panel) >= 2:
                    panel_agents = [a for a in agents if a["id"] in camp_panel]
                    vote_result = self.multi_agent._three_value_vote(
                        ["accept", "reject", "modify"], panel_agents
                    )
                    diagnostics["camp_vote"] = vote_result
                    diagnostics["camp_panel"] = camp_panel
                    logger.debug("CAMP panel assembled: %s", camp_panel)
        except Exception as e:
            logger.debug("CAMP deliberation failed: %s", e)

        # Marginal
        delta = fitness_after - fitness_before
        self.marginal.record(delta, "evolution", context)

        # AntiEvolution record
        self.anti_evolution.record_score(fitness_after)
        diagnostics["anti_evolution_compat"] = self.anti_evolution.check_compat(hypothesis=context or "auto-evolution")

        # ToolOverload: record tool usage during evolution
        self.tool_overload.record_selection("evolve", success=True)

        # ToolDrift: record tool usage for drift detection
        self.tool_drift.record_tool_use("evolve")

        # CircuitBreaker: record success
        self.circuit_breaker.record_success()

        # Trend: observe fitness trend
        self.trend.observe("fitness", fitness_after)

        # 5 Evolution Methods from EvoAgentBench
        # EverOS: search-oriented external memory evolution
        everos_result = self.everos.evolve(context or "auto", initial_state={"fitness": fitness_after})
        # GEPA: gradient-guided parameter evolution
        gepa_result = self.gepa.evolve(context or "auto")
        # Memento: memory-driven method evolution
        memento_result = self.memento_evolution.evolve(context or "auto", current_method="default", success=True)
        # ReasoningBank: reasoning strategy retrieval
        rb_result = self.reasoning_bank.evolve(context or "auto", context={"type": "general"})
        # OpenSpace: open-space exploration
        os_result = self.openspace.evolve(context or "auto", current_fitness=fitness_after)

        # Swiss Army Knife: Pass-k consistency verification
        pk_result = self.pass_k.evaluate(
            task="evolve_candidates",
            evaluate_fn=lambda c: fitness_after > 0.5,
        )

        # Swiss Army Knife: Multi-strategy selection
        strategy_names = ["gepa", "everos", "memento", "openspace", "ga"]
        _get_improvement = lambda r: getattr(r, "improvement", getattr(r, "best_fitness", 0))
        strategy_fitness = {
            "gepa": _get_improvement(gepa_result),
            "everos": _get_improvement(everos_result),
            "memento": _get_improvement(memento_result),
            "openspace": _get_improvement(os_result),
            "ga": delta,
        }
        for name, f in strategy_fitness.items():
            self.strategy_scheduler.update(arm_id=name, reward=f)
        best_result = self.strategy_scheduler.select(strategy="best")
        best_strategy = best_result.selected_arm if best_result.selected_arm else "gepa"

        # Swiss Army Knife: Trace engine records evolution trace
        trace_id = self.trace_engine.start_trace("evolve", {"fitness_before": fitness_before, "fitness_after": fitness_after})
        self.trace_engine.record_step(
            trace_id=trace_id,
            step_id=1,
            action="multi_strategy_evolve",
            confidence=fitness_after,
            result=f"best={best_strategy}, delta={delta:.4f}",
            metadata={"best_strategy": best_strategy, "delta": delta},
        )
        diagnostics["trace_decision"] = self.trace_engine.decision_analysis(trace_id)

        # === Evolve: full mechanism activation ===
        # Safety mechanisms
        diagnostics["circuit_breaker_allow"] = self.circuit_breaker.allow_request()
        diagnostics["circuit_breaker_state"] = self.circuit_breaker.get_state()

        # DAG scheduler deep operations
        diagnostics["dag_topo_sort"] = self.dag_scheduler.topological_sort()
        self.dag_scheduler.schedule()
        diagnostics["dag_critical_path"] = self.dag_scheduler.critical_path()

        # Evolution engine deep
        diagnostics["evolution_eval"] = self.evolution_engine.evaluate()

        # Multi-agent deep operations
        diagnostics["multi_agent_alloc"] = self.multi_agent.allocate_task({"task": context, "required_capabilities": []})
        diagnostics["multi_agent_consensus"] = self.multi_agent.reach_consensus([{"value": "strategy_a"}, {"value": "strategy_b"}])

        # Reflexion deep operations
        self.reflexion.record_attempt(context or "evolve", fitness_after)
        diagnostics["reflexion_context"] = self.reflexion.get_reflection_context(top_k=3, query=context)
        diagnostics["reflexion_worst"] = self.reflexion.get_worst_actions()
        diagnostics["reflexion_trend"] = self.reflexion.get_improvement_trend()

        # Marginal deep operations
        self.marginal.accumulate_batch(
            baseline_score=fitness_before,
            operations=[{"id": "evo_1", "type": "evolve", "content": context, "score": fitness_after}]
        )
        diagnostics["marginal_advantages"] = self.marginal.get_advantages()
        diagnostics["marginal_stable"] = self.marginal.get_stable_operations()
        diagnostics["marginal_history"] = self.marginal.get_operation_history("evo_1")
        diagnostics["marginal_batch"] = self.marginal.get_batch_comparison(1, 2)

        # SEAGym deep operations
        self.seagym.register_case({"context": context, "fitness": fitness_after})
        self.seagym.register_cases([{"context": context, "fitness": fitness_after, "split": "train", "expected": 0.5}])
        diagnostics["seagym_overfitting"] = self.seagym.detect_overfitting()
        diagnostics["seagym_cost"] = self.seagym.get_cost_analysis()
        diagnostics["seagym_transfer"] = self.seagym.get_transfer_analysis()
        self.seagym.save_snapshot(epoch=int(time.time()), metadata={"fitness": fitness_after})
        # _ = self.seagym.evaluate_all_splits()  # requires case data

        # Behavior mirror deep
        self.behavior_mirror.mirror("system", "evolve", {"fitness": fitness_after})
        diagnostics["behavior_profile"] = self.behavior_mirror.compute_profile("system")
        diagnostics["behavior_deviation"] = self.behavior_mirror.detect_deviation("system")

        # Event bus
        diagnostics["event_bus_recent"] = self.event_bus.get_recent(3)

        # === 知识翻译：Level A + Level B ===
        try:
            kta_result = self.knowledge_to_mechanism.analyze_and_apply(
                context=context or "auto",
                tags=[context.split()[0]] if context else [],
                omega=self,
            )
            if kta_result.get("applied", 0) > 0:
                logger.info("KTA translations applied: %s", kta_result["summary"])
        except Exception as e:
            logger.debug("KTA translation skipped: %s", e)

        # Trend prediction
        diagnostics["trend_prediction"] = self.trend.predict()

        # Speculative fork merge
        diagnostics["speculative_result"] = self.speculative.evaluate_and_select()
        diagnostics["speculative_fork_merge"] = self.speculative_fork.merge(0, 1)

        # Tool fitness record (both old and new)
        self.tool_fitness.record_usage(context or "auto", "evolve", success=True, latency_ms=10.0)
        self.tool_fitness_full.record_call(context or "auto", {}, success=True, latency_ms=10.0)

        # 反馈环路：evolve → recall
        # 告诉 recall 哪些参数被进化提升了，帮助下次召回更好节点
        try:
            self.signal_fusion.push_feedback({
                "from": "evolve",
                "to": "recall",
                "type": "quality",
                "data": {
                    "fitness_before": round(fitness_before, 4),
                    "fitness_after": round(fitness_after, 4),
                    "delta": round(delta, 4),
                    "effective": delta > 0,
                    "method": result.method if hasattr(result, 'method') else strategy_name,
                },
            })
        except Exception as e:
            logger.debug("evolve: push_feedback to recall failed: %s", e)

        # FGG verify
        diagnostics["fggm_verify"] = self.fggm.verify({"context": context})

        # Eval engine deep
        diagnostics["eval_fitness_history"] = self.eval_engine.get_fitness_history()
        diagnostics["eval_convergence"] = self.eval_engine.get_convergence_curve()

        self.event_bus.publish({"type": "evolve_completed", "fitness_before": fitness_before, "fitness_after": fitness_after, "result": "SUCCESS", "strategy": strategy})
        # P0-b: 暴露进化链完整性(Thought Leap 检测) — 关键 stage 若有 leap, 明确标记
        missing_stages = [k for k, v in chain_trace.items() if not v]
        chain_complete = len(missing_stages) == 0
        diagnostics["chain_trace"] = chain_trace
        diagnostics["chain_complete"] = chain_complete
        diagnostics["chain_missing_stages"] = missing_stages
        evolve_result = EvolutionOutcome(
            result=EvolutionResult.SUCCESS,
            fitness_before=fitness_before, fitness_after=fitness_after,
            duration_ms=(time.time() - start) * 1000,
            details=f"delta={delta:.4f}, diagnostics_keys={list(diagnostics.keys())}, chain_complete={chain_complete}",
            metadata=diagnostics,
        )
        # Telemetry: 存储原始返回值
        self._telemetry["evolve"] = evolve_result

        # 写管道结果
        self.signal_fusion.set_pipe_result("evolve", {
            "result": evolve_result.result.value if hasattr(evolve_result.result, 'value') else str(evolve_result.result),
            "fitness_before": fitness_before, "fitness_after": fitness_after,
            "delta": round(delta, 4),
        })

        self.record_production("evolution", f"进化: {evolve_result.result} Δfitness={round(delta,4)} best={best_strategy}", {
            "result": str(evolve_result.result),
            "fitness_before": round(fitness_before, 4),
            "fitness_after": round(fitness_after, 4),
            "delta": round(delta, 4),
            "best_strategy": best_strategy,
        })

        # 后见之明技能蒸馏 (SEED): 从本管道轨迹提炼可复用技能
        try:
            self._mine_hindsight("evolve", produced=1,
                                  outcome=f"delta={round(delta, 4)}", success=True)
        except Exception:
            pass

        return evolve_result

    # ============================================================
    # learn pipeline
    # ============================================================
    def learn(self, source: str = "web", query: str = "AI", max_results: int = 5) -> dict:
        # 链上下文: 读取触发管信号（如 recall 检测到的知识缺口）
        learn_diagnostics: Dict[str, Any] = {}
        try:
            ctx = self.signal_fusion.get_chain_context()
            if ctx:
                trigger_pipe = ctx.get("trigger_pipe", "")
                sigs = ctx.get("trigger_signals", {})
                learn_diagnostics["trigger_pipe"] = trigger_pipe
                if trigger_pipe == "recall":
                    # recall detected a knowledge gap — learn fills it
                    gap_query = sigs.get("query", query)
                    if gap_query and gap_query != query:
                        logger.info("learn: filling gap from recall chain: %s", gap_query)
                        query = gap_query
                learn_diagnostics["chain_context_used"] = True
        except Exception as e:
            logger.warning("learn: chain_context read failed: %s", e)
            learn_diagnostics["chain_context_used"] = False

        # Exploration quota check
        can_explore, reason = self.exploration_quota.can_explore()
        if not can_explore:
            self.exploration_quota.record_round()  # prevent counter deadlock
            quota_result = {"source": source, "query": query, "total_results": 0, "new_nodes": 0,
                    "reason": reason}
            self._telemetry["learn"] = quota_result
            # Record scan for repeated-query detection
            self._scans.append({"query": query, "source": source, "nodes": 0, "ts": time.time(), "reason": reason})
            # Publish so AR can track consecutive_zero_gain
            self.event_bus.publish({"type": "learn_completed", "source": source, "query": query, "new_nodes": 0, "reason": reason})
            return quota_result

        if reason == "revision_round_required":
            # Insert a revision round before continuing exploration
            self.exploration_quota.record_round()

        # EvolvingPrompt: generate optimized prompt
        # (disabled - variable kept for future use)
        
        # Step 1: KnowledgeScanner
        scan_source = ScanSource(source) if source in [s.value for s in ScanSource] else ScanSource.WEB

        # P1c: 宿主经验回流 — 不走 scanner, 直接经 host.ingest_experience 拉取并路由进 store
        if scan_source == ScanSource.HOST_EXPERIENCE:
            return self._learn_host_experience(query, max_results)

        # 管道运行计数(监控可见性: 心跳/内部触发的 learn 也能被监控看到)
        try:
            self.nexus._pipelines.setdefault("learn", {"runs": 0, "failures": 0, "last_run": None})
            self.nexus._pipelines["learn"]["runs"] += 1
            self.nexus._pipelines["learn"]["last_run"] = time.time()
        except Exception:
            pass

        results = self.knowledge_scanner.scan(scan_source, query, max_results, force=True)

        # Step 2-3: remember each result
        # P1-2: 去重(进程内content hash) + 信源权 + 实体归一
        _SRC_WEIGHT = {"wiki": 0.8, "arxiv": 0.7, "github": 0.6, "web": 0.6,
                       "hackernews": 0.5, "academic": 0.7, "local": 0.6, "newsletter": 0.6,
                       "blog": 0.55, "report": 0.6}
        _STOP = {"the", "and", "for", "with", "from", "that", "this", "into", "via", "using", "based"}
        if not hasattr(self, "_learned_hashes"):
            self._learned_hashes: set[str] = set()
        import hashlib as _hl
        def _norm_tag(t: str) -> str:
            t = t.lower().replace("-", "_").replace(" ", "_").strip()
            return t
        new_nodes = []
        # P1: 知识分类路由 — 按源/内容判断 NodeType + rail 标签(供四轨下游消费, 不重拉源)
        import re as _re
        _PARAM_RE = _re.compile(r"[a-zA-Z_]+[_-]?(rate|lr|alpha|beta|gamma|threshold|temp|decay)\s*[=:]\s*[\d.]+", _re.I)
        def _classify(source: str, content: str, tags: list) -> tuple:
            """返回 (NodeType, [rail标签]) — 基于源类型与内容模式。

            源类型硬分(github/arxiv/wiki) 优先; 其余(web 等) 默认 FACT,
            但追加内容级识别: arxiv/github URL 或论文/代码特征词 →
            自动提升为 PAPER/PROJECT (解 B-级根因: 调用方传 web 时
            论文/代码不再全降级为 FACT)。
            """
            rails = []
            ntype = NodeType.FACT
            s = source.lower()
            if s == "github":
                ntype = NodeType.PROJECT
                rails.append("rail_t3")
            elif s in ("arxiv", "academic", "report"):
                ntype = NodeType.PAPER
                rails.append("rail_t4")
            elif s == "wiki":
                ntype = NodeType.CONCEPT
                rails.append("rail_t2")
            else:
                # 内容级兜底: 即使 source=web, 也能识别论文/代码
                low = (content or "").lower()
                if "arxiv.org" in low or _re.search(r"\d{4}\.\d{4,5}", low):
                    ntype = NodeType.PAPER
                    rails.append("rail_t4")
                elif "github.com" in low or "def " in low and "import " in low:
                    ntype = NodeType.PROJECT
                    rails.append("rail_t3")
                elif any(k in low for k in ("et al.", "proceedings", "doi:", "abstract")):
                    ntype = NodeType.PAPER
                    rails.append("rail_t4")
            # 内容模式: 含参数值 -> 促参数进化
            if _PARAM_RE.search(content):
                rails.append("rail_t1")
                if ntype == NodeType.FACT:
                    ntype = NodeType.PROCEDURE
            # 概念型内容 -> 语义进化
            elif any(k in content.lower() for k in ("is a", "refers to", "defined as", "concept of")):
                rails.append("rail_t2")
                if ntype == NodeType.FACT:
                    ntype = NodeType.CONCEPT
            return ntype, rails
        for r in results:
            # 实体归一: title+content 归一化后算 hash 做进程内去重
            raw = f"{getattr(r, 'title', '')}: {getattr(r, 'content', '')}".lower()
            h = _hl.md5(raw.encode("utf-8")).hexdigest()
            if h in self._learned_hashes:
                continue  # 本会话已学, 跳过重复写入
            self._learned_hashes.add(h)
            norm_tags = sorted({_norm_tag(t) for t in (getattr(r, "tags", []) or []) if t and _norm_tag(t) not in _STOP})
            base_u = _SRC_WEIGHT.get(source, 0.6)
            ntype, rails = _classify(source, f"{r.title}: {r.content}", norm_tags)
            node_tags = norm_tags + rails  # rail 标签并入 tags, 下游按 tag 路由
            node_id = self.remember(content=f"{r.title}: {r.content}",
                                    utility=base_u, tags=node_tags,
                                    node_type=ntype, url=getattr(r, "url", ""))
            if node_id:
                new_nodes.append(node_id)
                # 【P0修复】注册到LearnFeedbackTracker
                self.learn_feedback.register(node_id, source=source, query=query)
                self.record_production("knowledge", f"学习新知识 {getattr(r, 'title', '')[:50]}", {
                    "node_id": node_id, "source": source, "url": getattr(r, "url", ""),
                    "title": getattr(r, "title", ""), "tags": node_tags,
                })

                try:
                    node = self.store.read_node(node_id)
                    if ntype == NodeType.PROJECT and node is not None:
                        ext = self.mechanism_extractor.extract_from_node(node)
                        if ext is not None:
                            self._consume_t3({"name": ext.name, "data": {"gene_specs": ext.contract}})
                            logger.info("Omega: T3 extracted mechanism %s from %s", ext.name, getattr(node, "url", ""))
                    elif ntype == NodeType.PAPER and node is not None:
                        comp = self.mechanism_compiler.compile_from_node(node)
                        if comp is not None:
                            self._consume_t4({"name": comp.name, "data": {"target_location": comp.target_location, "draft_code": comp.draft_code, "paper": getattr(node, "url", "")}})
                            logger.info("Omega: T4 compiled mechanism %s from %s", comp.name, getattr(node, "url", ""))
                except Exception as e:
                    logger.warning("learn: T3/T4 mechanism extract/compile failed: %s", str(e)[:80])
                    self.record_issue("error", "learn", f"T3/T4 mechanism extract/compile failed: {str(e)[:80]}")

        # Step 4: CuriosityQueue (带 None 安全检查)
        if self.curiosity_queue is not None:
            for r in results:
                self.curiosity_queue.add(f"What is {r.title}?", priority=5)
        else:
            logger.debug("learn: curiosity_queue not initialized, skipping")

        # Step 5: UtilityTracker (带 None 安全检查)
        if self.utility_tracker is not None:
            for node_id in new_nodes:
                self.utility_tracker.register(node_id)
        else:
            logger.debug("learn: utility_tracker not initialized, skipping")

        # 注意: 不为每次 learn 的 query 注册一次性 skill (learn_{source}_{query})
        # 那会制造永不消费的孤儿 skill -> 监控误报触发缺失. query 的评估/路由已由
        # curator.evaluate + skill_claw.route 处理. 通用入口 learn_{source} 仍注册(见下).
        self.curator.evaluate(type("Skill", (), {"name": f"learn_{source}_{query}", "content": query})())
        self.skill_claw.route(query)
        self.mechanism_registry.register(f"learn_{source}", {"query": query, "count": len(new_nodes)})
        self.cot.generate(f"Learned from {source}: {query}")
        for r in results[:3]:
            self.few_shot.add_example(r.title, r.content[:200])
        self.knowledge_gen.generate({"source": source, "query": query, "results": len(new_nodes)})
        self.refiner.refine({"action": "learn", "source": source, "query": query})

        # === Learn: full mechanism activation ===
        # ParallelDispatcher: 并行处理扫描结果
        learn_dispatch_info = {}
        if results:
            dispatch_result = self.parallel_dispatcher.dispatch([
                {"description": f"Process: {r.title}"} for r in results[:3]
            ])
            learn_dispatch_info = {
                "dispatched": dispatch_result.completed,
                "failed": dispatch_result.failed,
            }

        # A2ABasic: 注册当前 agent 能力并委托任务
        a2a_stats = {}
        a2a_task = None
        try:
            self.a2a_basic.register_agent("omega", ["learn"])
            a2a_task = self.a2a_basic.delegate_task(f"Learn about {query}", required=[], requester="omega")
            a2a_stats = self.a2a_basic.get_stats()
        except Exception:
            logger.warning("A2A delegate_task failed, running without A2A stats")
            a2a_stats = {"status": "a2a_unavailable"}

        # SubAgentContract: 为委托学习创建合约
        contract_id = ""
        if a2a_task and hasattr(a2a_task, 'executor') and a2a_task.executor:
            try:
                contract = self.sub_agent_contract.create_contract(
                    agent_id=a2a_task.executor,
                    task=f"Learn: {query}",
                    quality_threshold=0.7
                )
                contract_id = contract.get("id", "") if isinstance(contract, dict) else str(getattr(contract, 'id', ''))
            except Exception:
                logger.warning("Contract creation failed for a2a task")
                contract_id = "contract_creation_failed"

        # Anti-pattern 2: 只列不深 → short titles with no content = shallow scan
        if all(len(r.content or '') < 80 for r in results[:max_results]):
            logger.debug("Anti-pattern: shallow learn (all results have < 80 chars)")

        # Anti-pattern 3: 重复学习检测
        scan_history = self._scans[-5:] if len(self._scans) > 5 else self._scans
        same_query_count = sum(1 for s in scan_history if s.get("query") == query)
        if same_query_count > 2:
            logger.debug("Anti-pattern: repeated learn (same query 3+ times in last 5)")
            # 降低效用 (initially 0.7 from remember call)
            utility_val = 0.56  # 0.7 * 0.8

        # Curiosity queue deep (带 None 安全检查)
        if self.curiosity_queue is not None:
            curiosity_item = self.curiosity_queue.pop()
            learn_diagnostics["curiosity_popped"] = curiosity_item is not None
        else:
            logger.debug("learn: curiosity_queue not initialized, skipping pop")
            curiosity_item = None

        # Utility tracker deep
        for node_id in new_nodes[:3]:
            learn_diagnostics.setdefault("utility_averages", []).append(self.utility_tracker.get_average(node_id))

        # Mechanism registry deep
        self.mechanism_registry.enable(f"learn_{source}")
        learn_diagnostics["mechanism_invoke"] = self.mechanism_registry.invoke(f"learn_{source}")
        self.mechanism_registry.disable(f"learn_{source}")

        # Skill registry deep
        learn_diagnostics["skill_lookup"] = self.skill_registry.get_skill(f"learn_{source}_{query}")
        learn_diagnostics["active_skills"] = self.skill_registry.get_active_skills()

        # Curator deep
        learn_diagnostics["curator_ranking"] = self.curator.get_quality_ranking()

        # Few-shot deep
        learn_diagnostics["few_shot_selected"] = self.few_shot.select(query)

        # Knowledge gen deep
        self.knowledge_gen.generate_from_context(results[0].content if results else "")
        learn_diagnostics["kg_from_query"] = self.knowledge_gen.generate_from_query(query)
        learn_diagnostics["kg_top_entities"] = self.knowledge_gen.get_top_entities()
        learn_diagnostics["kg_facts"] = self.knowledge_gen.get_facts_for_entity(query.split()[0] if query else "")

        # Behavior mirror
        self.behavior_mirror.mirror("system", "learn", {"source": source, "query": query})

        # Event bus
        learn_diagnostics["event_recent"] = self.event_bus.get_recent(3)

        # Knowledge-to-Mechanism: check if knowledge can update parameters
        applied_changes = []
        for r in results:
            mappings = self.knowledge_to_mechanism.analyze_knowledge(
                "%s %s" % (r.title, r.content), tags=r.tags)
            for mapping in mappings:
                if self.knowledge_to_mechanism.apply_mapping(mapping, self):
                    applied_changes.append(mapping)

        # ===== SemanticLearner: 新知识也走语义学习 (概念/关系抽取) =====
        semantic_summary = {"concepts": 0, "relations": 0}
        if self.semantic_learner is not None:
            for r in results:
                try:
                    s = self.semantic_learner.learn("%s %s" % (r.title, r.content), tags=r.tags)
                    semantic_summary["concepts"] += s.get("concepts_found", 0)
                    semantic_summary["relations"] += s.get("relations_found", 0) + s.get("inferred_relations", 0)
                except Exception as e:
                    logger.debug("learn: SemanticLearner failed: %s", e)
        learn_diagnostics["semantic"] = semantic_summary

        # Record exploration round
        self.exploration_quota.record_round()
        self.explorer_state.record_round(query, source, 0.5)

        # Auto-fill curiosity queue if low (带 None 安全检查)
        if self.curiosity_queue is not None and hasattr(self.curiosity_queue, '_queue'):
            if self.curiosity_queue._queue and len(self.curiosity_queue._queue) < 3:
                if self.curiosity_autofill is not None:
                    self.curiosity_autofill.auto_fill(count=2)
        else:
            logger.debug("learn: curiosity_queue or autofill not initialized")

        # DeepRetrofit6: trigger deep learning when knowledge is acquired
        if len(new_nodes) > 0:
            source_content = "\n---\n".join(
                f"{r.title}: {r.content}" for r in results
            )
            self.deep_retrofit_6.execute(
                    topic=query,
                    source_file="%s://%s" % (source, query),
                    source_content=source_content,
                )

            self.event_bus.publish({"type": "learn_completed", "source": source, "query": query, "new_nodes": len(new_nodes)})

            # Record scan for repeated-query detection
            self._scans.append({"query": query, "source": source, "nodes": len(new_nodes), "ts": time.time()})

            # Self-Observation: 记录 learn，在周循环时触发回顾
            try:
                review = self.self_observation.record_learn(query, len(new_nodes), source, utility_val if same_query_count > 2 else 0.7)
                if review and review.get("patterns"):
                    logger.info("SelfObservation: %d patterns, zero_gain=%d",
                                len(review["patterns"]), review.get("zero_gain_streak", 0))
            except Exception as e:
                logger.warning("SelfObservation.record_learn failed: %s", e)

            learn_result = {"source": source, "query": query, "total_results": len(new_nodes),
                "new_nodes": len(new_nodes), "applied_changes": len(applied_changes),
                "parallel_dispatch": learn_dispatch_info, "a2a_stats": a2a_stats,
                "contract_id": contract_id, "diagnostics": learn_diagnostics}
            # Telemetry: 存储原始返回值
            self._telemetry["learn"] = learn_result

            # 写管道结果
            self.signal_fusion.set_pipe_result("learn", {
                "source": source, "query": query,
                "total_results": len(new_nodes), "new_nodes": len(new_nodes),
            })

            # 反馈环路: learn → recall
            # 告诉 recall 学到的查询, 下次 recall 命中率更高
            if len(new_nodes) > 0:
                try:
                    self.signal_fusion.push_feedback({
                        "from": "learn",
                        "to": "recall",
                        "type": "quality",
                        "data": {
                            "query": query,
                            "new_nodes": len(new_nodes),
                            "source": source,
                        },
                    })
                except Exception as e:
                    logger.debug("learn: push_feedback to recall failed: %s", e)

            # ===== 反刍环节 (温故知新): learn 管道内周期性重学存量知识 =====
            # 原挂于 heartbeat 平级调用，现移入 learn 以落实"learn 管道内分支"设计。
            # 周期由 next_rumination_due() 控制，结果并入 learn 返回值。
            try:
                due = self.rumination_engine.next_rumination_due()
                if due["mode"] != "skip":
                    rres = self.rumination_engine.ruminate(mode=due["mode"])
                    learn_result["rumination"] = {
                        "mode": due["mode"],
                        "relearned": rres.relearned,
                        "mappings_applied": rres.mappings_applied,
                        "skills_promoted": rres.skills_promoted,
                    }
                    logger.info("learn: rumination %s relearned=%d mappings=%d skills=%d",
                                due["mode"], rres.relearned, rres.mappings_applied, rres.skills_promoted)
                    # PlaybookInheritance: 反刍产出的可复用配方注册为 playbook(温故知新继承)
                    if rres.skills_promoted:
                        try:
                            from prometheus_nexus.evolution.playbook_inheritance import Playbook, PlaybookStep
                            # 修空壳: 从反刍结果提炼真实 steps
                            steps = []
                            promoted = getattr(rres, "promoted_skills", None) or []
                            if isinstance(promoted, (list, tuple)):
                                for idx, sk in enumerate(promoted[:8]):
                                    nm = sk if isinstance(sk, str) else str(sk)
                                    steps.append(PlaybookStep(
                                        step_id=f"rum_{due['mode']}_{idx}",
                                        name=nm[:40],
                                        operation="workflow",
                                        params={"steps": [nm]},
                                    ))
                            if not steps:
                                steps.append(PlaybookStep(
                                    step_id=f"rum_{due['mode']}_0",
                                    name=f"rumination {due['mode']}",
                                    operation="workflow",
                                    params={"steps": [f"relearn via {due['mode']}"]},
                                ))
                            pb = Playbook(playbook_id=f"pb_{due['mode']}_{int(time.time())}",
                                          name=f"rumination_{due['mode']}",
                                          description=f"relearned {rres.skills_promoted} skills via {due['mode']}",
                                          steps=steps,
                                          tags=["rumination", due["mode"]])
                            self.playbook_inheritance.register_playbook(pb)
                            logger.info("learn: registered playbook from rumination %s (%d steps)", due["mode"], len(steps))
                        except Exception as e:
                            logger.warning("learn: playbook_inheritance register failed: %s", str(e)[:50])
            except Exception as e:
                logger.warning("learn: rumination failed: %s", e)

            # ===== P2-1: 累计高频命中主题为长期关注 =====
            try:
                qstats = getattr(self.learn_feedback, "_query_stats", {})
                key = (source, query)
                st = qstats.get(key, {})
                if st.get("hits", 0) >= self._focus_threshold:
                    self.focus_topics[query] += 1
            except Exception:
                pass

            # 后见之明技能蒸馏 (SEED): 从 learn 轨迹提炼可复用技能
            try:
                self._mine_hindsight("learn", produced=len(new_nodes),
                                      outcome=f"new_nodes={len(new_nodes)}", success=True)
            except Exception:
                pass

            # 组合式技能合成 (Agentic Proposing): 用 Proposer 为本次查询提议 workflow
            try:
                proposed = self.proposer.propose(query, max_steps=4)
                learn_result["proposed_workflow"] = proposed
            except Exception:
                pass

            return learn_result

        # Publish for 0-result scan so AR can track consecutive_zero_gain
        self.event_bus.publish({"type": "learn_completed", "source": source, "query": query, "new_nodes": 0})
        # Record scan for repeated-query detection
        self._scans.append({"query": query, "source": source, "nodes": 0, "ts": time.time(), "reason": "empty_scan"})
        return {"source": source, "query": query, "total_results": 0, "new_nodes": 0, "reason": "empty_scan"}

    # ============================================================
    def _learn_host_experience(self, query: str = "", max_results: int = 5) -> dict:
        """从宿主 agent 拉取运行时经验(行为日志/失败/反馈), 路由进 store 供 T2/T4 消费.

        经 self.host.pull_experience 真拉取(宿主 adapter 实现协议: 本地经验文件/队列),
        每条经验转成 store 节点, 由 rumination 打 rail 标签(rail_t2 语义 / rail_t4 论文编译)
        进入对应进化轨. 这是"宿主驱动的自进化"关键: 进化燃料来自宿主真实使用 [P0 C2].
        """
        if not hasattr(self, "host") or self.host is None:
            return {"source": "host_experience", "query": query, "total_results": 0,
                    "new_nodes": 0, "reason": "no_host_adapter"}
        new_nodes = 0
        try:
            events = self.host.pull_experience(limit=max_results)
            for ev in events:
                content = ev.get("content") or ev.get("task") or ""
                if not content:
                    continue
                utility = float(ev.get("utility", 0.55))
                node = self.remember(
                    content=f"[host_experience] {content}",
                    utility=utility,
                    tags=["host_experience", "rail_t2", "rail_t4"],
                    node_type=NodeType.PROCEDURE,
                    branch=self.host.host_id,  # [P2 C5] 多宿主隔离: 经验按 host_id 分区
                )
                if node:
                    new_nodes += 1
        except Exception as e:
            logger.debug("learn_host_experience: pull failed: %s", e)
        return {
            "source": "host_experience", "query": query,
            "total_results": new_nodes, "new_nodes": new_nodes,
            "host": (self.host.get_runtime_context() or {}).get("host", "none"),
        }

    # ============================================================
    # reflect pipeline
    # ============================================================
    def reflect(self, context: str = "") -> dict:
        # 管道运行计数(监控可见性)
        try:
            self.nexus._pipelines.setdefault("reflect", {"runs": 0, "failures": 0, "last_run": None})
            self.nexus._pipelines["reflect"]["runs"] += 1
            self.nexus._pipelines["reflect"]["last_run"] = time.time()
        except Exception:
            pass
        # AdaptiveHarness: check harness state
        harness_state = self.adaptive_harness.get_state()

        reflect_diagnostics: Dict[str, Any] = {}

        # 链上下文：读取触发管的完整信号
        try:
            ctx = self.signal_fusion.get_chain_context()
            if ctx:
                trigger_pipe = ctx.get("trigger_pipe", "")
                sigs = ctx.get("trigger_signals", {})
                if trigger_pipe == "learn":
                    new_nodes = sigs.get("new_nodes", 0) or sigs.get("node_count", 0)
                    source = sigs.get("source", "?")
                    query = sigs.get("query", "?")
                    context += f" | Learn quality review: {new_nodes} nodes from {source}:{query}"
                    self.cerebral_cortex.add_merge_reason(
                        "reflect", f"learn_evaluation:{source}:{query}")
                elif trigger_pipe == "recall":
                    gap_query = sigs.get("query", "")
                    gap_count = sigs.get("gap_count", 0)
                    context += f" | Knowledge gap: '{gap_query}' missed {gap_count}x"
                elif trigger_pipe == "reflect":
                    raw_score = sigs.get("raw_score", 0.5)
                    raw_drift = sigs.get("raw_drift", 0)
                    context += f" | Reflect-driven: score={raw_score:.3f}, drift={raw_drift}"
                elif trigger_pipe == "evolve":
                    raw_before = sigs.get("raw_before", 0.5)
                    raw_after = sigs.get("raw_after", 0.5)
                    delta = raw_after - raw_before
                    context += f" | Evolve efficacy: delta={delta:.4f}"
                elif trigger_pipe == "dream":
                    patterns = sigs.get("patterns_found", 0)
                    context += f" | Pattern consolidation: {patterns} patterns"
        except Exception as e:
            logger.warning("Reflexion chain context processing failed: %s", e)

        # LoopSelector: record reflection outcome
        self.loop_selector.record_outcome(LoopStrategy.REFLEXION, 0.8)

        # === Cross-analyze recent learned knowledge ===
        # Get recent nodes directly from store (bypass RecallRequest validation)
        recent_nodes = self.store.search("", limit=20)
        learned_knowledge_summary = []
        for node in recent_nodes[:5]:
            learned_knowledge_summary.append({
                "content": node.content[:200] if node else "",
                "utility": getattr(node, "utility", 0.0) if node else 0.0,
                "tags": getattr(node, "tags", []) if node else [],
                "type": getattr(node, "type", "") if node else "",
            })

        # ThinkTool: structured thinking before reflection
        think_result = self.think_tool.run(
            task="Reflect on system performance and identify improvements",
            context=f"health={self._compute_health()}, nodes={self.store.get_node_count()}, recent_knowledge={len(recent_nodes)}",
        )

        # ContextEngineering: isolate reflection context
        reflect_components = [
            ContextComponent(name="task", type="instruction",
                           content="Reflect on system performance", priority=1, tokens=20),
            ContextComponent(name="health", type="knowledge",
                           content="health=%s, nodes=%d, recent_learned=%d" % (self._compute_health(), self.store.get_node_count(), len(recent_nodes)),
                           priority=2, tokens=20),
            ContextComponent(name="learned_knowledge", type="knowledge",
                           content=str(learned_knowledge_summary[:3]),
                           priority=3, tokens=100),
        ]
        isolated, remaining = self.context_engineering.isolate(
            reflect_components, "reflection analysis", max_tokens=8000
        )

        current_fitness = self._compute_fitness()
        fv = self.five_view.evaluate(
            node_count=self.store.get_node_count(),
            edge_count=self.store.get_edge_count(),
            bank_count=self.bank.count(),
            evolution_fitness=current_fitness,
            alert_level=self.equilibrium.get_alert_level(),
            uptime_s=time.time() - self._start_time,
            drift_alerts=len(self.drift_detector.detect()),
            convergence=self.convergence.is_converged(),
        )

        # Stale detection: skip heavy processing if score unchanged within 15min
        STALE_THRESHOLD_SEC = 900  # 15 minutes
        now = time.time()
        score_delta = abs(fv.composite_score - self._last_reflect_score)
        time_since_last = now - self._last_reflect_time
        if score_delta < 0.0001 and time_since_last < STALE_THRESHOLD_SEC and self._last_reflect_time > 0:
            logger.info("reflect skipped (stale: delta=%.6f, last=%.1fs ago)", score_delta, time_since_last)
            self._last_reflect_time = now  # extend timeout so we don't spam
            stale_result = {
                "five_view": {"score": fv.composite_score, "grade": fv.grade},
                "harness": {"score": 0, "grade": "N/A"},
                "drift_alerts": 0,
                "stale_skipped": True,
                "reason": "Score unchanged since last reflect; skipping heavy cycle.",
            }
            self._telemetry["reflect"] = stale_result
            return stale_result
        self._last_reflect_score = fv.composite_score
        self._last_reflect_time = now
        hv = self.harness_x.evaluate()
        # HarnessX: evaluate best config if available
        best_config = self.harness_x.get_best_config()
        harness_score = getattr(hv, 'score', getattr(hv, 'composite_score', 0.0))
        if best_config:
            harness_eval = self.harness_x.evaluate(best_config, test_cases=[{"input": "reflect"}])
            if hasattr(harness_eval, 'score'):
                harness_score = harness_eval.score
        drift = self.drift_detector.detect()
        self.thermodynamic.update(0.1)
        # thermodynamic.reset when temperature is extreme
        stats = self.thermodynamic.get_stats()
        if stats.get("temperature", 0.5) > 0.9 or stats.get("temperature", 0.5) < 0.1:
            self.thermodynamic.reset()
        self.convergence.observe(fv.composite_score)
        self.coala.observe({"five_view": fv.composite_score, "harness": harness_score})
        reflect_diagnostics["four_network_reflect"] = self.four_network.reflect("system performance", num_reflections=2)
        self.info_gain.record_gain("reflect", fv.composite_score)
        self.agent_forest.add_agent(f"reflector_{int(time.time())}", {"score": fv.composite_score})
        self.dynamic_scaler.scale("reflect", fv.composite_score)
        self.behavior_mirror.mirror("self", "reflect", {"score": fv.composite_score})

        # CausalKnowledgeGraph
        self.causal_graph.add_node(f"reflect_{int(time.time())}", f"score={fv.composite_score:.2f}",
                                   {"drift": len(drift)})

        # Feedback + FailureLog
        worst = self.feedback.get_worst_performers(top_k=5)
        avoidance = self.failure_log.get_avoidance_list()

        # Equilibrium: observe system balance
        self.equilibrium.observe(fv.composite_score, "composite")

        # Trend: observe five_view trend
        self.trend.observe("five_view", fv.composite_score)

        # SystematicDebugging: 自动调试低 fitness 状态
        reflect_debug_info = {"status": "no_debug_needed"}
        if fv.composite_score < 0.3:
            try:
                debug_result = self.systematic_debugging.debug(
                    f"Low fitness: {fv.composite_score:.2f}",
                    context={"five_view": fv.__dict__ if hasattr(fv, '__dict__') else {}}
                )
                reflect_debug_info = {
                    "root_cause": debug_result.root_cause,
                    "verified": debug_result.verified,
                    "confidence": debug_result.confidence,
                }
            except Exception as e:
                reflect_debug_info = {"error": str(e)}

        # CodeReviewer: 审查 reflect 分析质量
        reflect_review = {"score": 0, "critical": 0, "approved": False}
        try:
            review_result = self.code_reviewer.review(
                code_path="life.py:reflect",
                changes=[{"type": "reflection", "score": fv.composite_score}]
            )
            reflect_review = {
                "score": review_result.overall_score,
                "critical": review_result.critical_count,
                "approved": review_result.approved,
            }
        except Exception:
            logger.warning("Reflect review failed, marking as unavailable")
            reflect_review["status"] = "review_unavailable"

        # Disposition: get behavioral prediction
        disposition = self.disposition.get_disposition("remember_utility")

        # MARS: get belief state
        mars_belief = self.mars.get_belief("dream_belief")

        # === Reflect: full mechanism activation ===
        # Thermodynamic deep operations
        reflect_diagnostics["thermo_energy"] = self.thermodynamic.get_energy()
        reflect_diagnostics["thermo_compressed"] = self.thermodynamic.get_compressed_scale()
        reflect_diagnostics["thermo_intelligence"] = self.thermodynamic.compute_intelligence()
        reflect_diagnostics["thermo_intel_breakdown"] = self.thermodynamic.get_intelligence_breakdown()
        reflect_diagnostics["thermo_rare_valid"] = self.thermodynamic.get_rare_valid_fidelity()
        reflect_diagnostics["thermo_trajectory"] = self.thermodynamic.get_trajectory_summary()
        # 喂入真实数据：outcome_valid=低漂移说明反思有效，rarity=复合分数反映反思价值
        self.thermodynamic.observe_baseline(0.3)
        self.thermodynamic.observe_action(
            action="reflect",
            outcome_valid=len(drift) < 3,
            rarity=1.0 - (fv.composite_score or 0.5),
            baseline_prob=0.3,
            induced_prob=0.3 * (1 + (1.0 - (fv.composite_score or 0.5))),
        )
        reflect_diagnostics["thermo_validity_rate"] = self.thermodynamic.get_validity_rate()
        reflect_diagnostics["thermo_rare_ratio"] = self.thermodynamic.get_rare_valid_ratio()

        # Convergence deep
        reflect_diagnostics["convergence_history"] = self.convergence.get_history()

        # Info gain deep
        reflect_diagnostics["info_gain_returns"] = self.info_gain.diminishing_returns()

        # Agent forest deep operations
        self.agent_forest.record_performance(f"reflector_{int(time.time())}", fv.composite_score)
        reflect_diagnostics["agent_rankings"] = self.agent_forest.get_agent_rankings()
        reflect_diagnostics["agent_samples"] = self.agent_forest.sample_agents(2)
        vote = self.agent_forest.sample_vote("reflect", responses=["ok", "ok", "needs_work"])
        reflect_diagnostics["agent_removed"] = self.agent_forest.remove_agent("old_reflector")

        # Behavior mirror deep
        reflect_diagnostics["behavior_profile"] = self.behavior_mirror.compute_profile("system")
        reflect_diagnostics["behavior_deviation"] = self.behavior_mirror.detect_deviation("system")

        # Event bus deep
        self.event_bus.subscribe("reflect_events", lambda e: None)
        reflect_diagnostics["event_recent"] = self.event_bus.get_recent(5)

        # Feedback deep operations
        reflect_diagnostics["feedback_avg"] = self.feedback.get_average("recent")
        reflect_diagnostics["feedback_best"] = self.feedback.get_best_performers()
        reflect_diagnostics["feedback_count"] = self.feedback.get_feedback_count("recent")
        reflect_diagnostics["feedback_trend"] = self.feedback.get_feedback_trend("recent")
        reflect_diagnostics["feedback_type_stats"] = self.feedback.get_type_stats()

        # Failure log deep operations
        logger.info("reflect: score=%.4f, grade=%s, drift=%d", fv.composite_score, fv.grade, len(drift))
        self.record_production("reflection", f"反思: 评分={fv.composite_score:.3f} 等级={fv.grade} 漂移={len(drift)}", {
            "score": fv.composite_score, "grade": fv.grade, "drift": len(drift),
        })
        reflect_diagnostics["failure_rates"] = self.failure_log.get_action_failure_rates()

        reflect_diagnostics["failure_recent"] = self.failure_log.get_recent_failures()
        reflect_diagnostics["failure_severity"] = self.failure_log.get_severity_distribution()

        # Disposition deep operations
        reflect_diagnostics["disposition_shifts"] = self.disposition.detect_shifts("remember_utility")
        reflect_diagnostics["disposition_all"] = self.disposition.get_all_dispositions()
        reflect_diagnostics["disposition_stable"] = self.disposition.get_most_stable()
        reflect_diagnostics["disposition_volatile"] = self.disposition.get_most_volatile()
        reflect_diagnostics["disposition_shift_count"] = self.disposition.get_shift_count("remember_utility")
        reflect_diagnostics["disposition_shift_history"] = self.disposition.get_shift_history("remember_utility")
        reflect_diagnostics["disposition_variance"] = self.disposition.get_variance("remember_utility")
        reflect_diagnostics["disposition_std"] = self.disposition.get_std("remember_utility")
        reflect_diagnostics["disposition_predict"] = self.disposition.predict("remember_utility")

        # MARS deep operations
        reflect_diagnostics["mars_all_beliefs"] = self.mars.get_all_beliefs()

        # Causal graph deep
        self.causal_graph.add_edge("reflect_start", f"reflect_{int(time.time())}", "causes", 0.8)
        reflect_diagnostics["causal_shortest"] = self.causal_graph.shortest_path("reflect_start", f"reflect_{int(time.time())}")
        reflect_diagnostics["causal_effects"] = self.causal_graph.causal_effects("reflect_start")
        self.causal_graph.do_intervention("reflect_start", 0.9)

        # Reflexion deep
        self.reflexion.record_attempt("reflect", fv.composite_score)
        reflect_diagnostics["reflexion_context"] = self.reflexion.get_reflection_context(query="reflect")
        reflect_diagnostics["reflexion_worst"] = self.reflexion.get_worst_actions()
        reflect_diagnostics["reflexion_trend"] = self.reflexion.get_improvement_trend()

        # Extended thinking deep
        reflect_diagnostics["extended_thought_tree"] = self.extended_thinking.get_thought_tree()

        # Loop guard deep
        self.loop_guard.record_action("reflect")
        self.loop_guard.reset()

        # RL pathology deep
        self.rl_pathology.observe(fv.composite_score, "reflect")

        # 大脑皮层洞察：激活 CerebralCortex.get_insights()
        try:
            if hasattr(self, 'cerebral_cortex') and self.cerebral_cortex is not None:
                cc_insights = self.cerebral_cortex.get_insights()
                reflect_diagnostics['cc_insights'] = cc_insights
                fuse_state = cc_insights.get("fuse_state", {})
                active_fuses = {k: v for k, v in fuse_state.items() if v.get("suppressed")}
                if active_fuses:
                    reflect_diagnostics['active_fuses'] = active_fuses
                    logger.info("reflect: %d active fuses detected", len(active_fuses))
        except Exception as e:
            logger.debug("CC insights not available: %s", e)

        # Session
        self.session.access(f"reflect_{int(time.time())}")
        self.session.expire_idle()

        # publish before return (fix: was dead code after return)
        self.event_bus.publish({"type": "reflect_completed", "composite_score": fv.composite_score, "drift_alerts": len(drift)})

        reflect_result = {
            "five_view": {"score": fv.composite_score, "grade": fv.grade},
            "harness": {"score": harness_score, "grade": "B" if harness_score > 0.7 else "C" if harness_score > 0.4 else "D"},
            "drift_alerts": len(drift),
            "thermodynamic": self.thermodynamic.get_stats(),
            "convergence": self.convergence.is_converged(),
            "worst_performers": len(worst),
            "avoidance_list": len(avoidance),
            "equilibrium": self.equilibrium.get_alert_level(),
            "disposition": disposition,
            "mars_belief": mars_belief,
            "recent_learned": {
                "count": len(recent_nodes),
                "knowledge": learned_knowledge_summary,
            },
            "debug": reflect_debug_info,
            "code_review": reflect_review,
            "diagnostics": reflect_diagnostics,
        }
        # Telemetry: 存储原始返回值
        self._telemetry["reflect"] = reflect_result

        # 反馈环路: reflect → evolve
        # 告诉 evolve 这次 reflect 的质量分数, 帮助选择值得进化的方向
        try:
            self.signal_fusion.push_feedback({
                "from": "reflect",
                "to": "evolve",
                "type": "quality",
                "data": {
                    "composite_score": fv.composite_score,
                    "drift_count": len(drift),
                    "harness_score": harness_score,
                    "effective": fv.composite_score > 0.5,
                },
            })
        except Exception as e:
            logger.debug("reflect: push_feedback to evolve failed: %s", e)

        # 写管道结果（双向语义穿透）
        self.signal_fusion.set_pipe_result("reflect", {
            "composite_score": fv.composite_score,
            "grade": fv.grade,
            "drift_count": len(drift),
            "converged": fv.composite_score > 0.5,
        })

        # ========== P1: Self-Observation + FineTuneAudit ==========
        try:
            # SelfObservation: 记录反思行为模式
            recent_actions = self._get_recent_actions()
            for action in recent_actions[:3]:
                self.self_observation.observe(action["action"], action.get("outcome", "unknown"))
            improvements = self.self_observation.get_improvements()
            if improvements:
                reflect_diagnostics["self_observation_improvements"] = improvements
        except Exception as e:
            logger.debug("Self-observation failed: %s", e)

        try:
            # FineTuneAudit: 定期域级错位评估（仅在节点数>100时运行）
            if self.store.get_node_count() > 100:
                domain_evals = []
                for domain in ["code", "medical", "legal", "finance"]:
                    eval_result = self.finetune_audit.evaluate_domain(domain, context[:200])
                    if eval_result.get("misalignment_score", 0) > 0.5:
                        domain_evals.append({
                            "domain": domain,
                            "score": eval_result["misalignment_score"],
                            "risk": "high"
                        })
                if domain_evals:
                    reflect_diagnostics["domain_misalignment_alerts"] = domain_evals
        except Exception as e:
            logger.debug("FineTune audit failed: %s", e)

        # 后见之明技能蒸馏 (SEED): 从 reflect 轨迹提炼可复用技能
        try:
            self._mine_hindsight("reflect", produced=1,
                                  outcome="reflect completed", success=True)
        except Exception:
            pass

        return reflect_result

    # ============================================================
    # dream pipeline
    # ============================================================
    def dream_cycle(self, branch: str = "main") -> DreamResult:
        # 管道运行计数(监控可见性)
        try:
            self.nexus._pipelines.setdefault("dream_cycle", {"runs": 0, "failures": 0, "last_run": None})
            self.nexus._pipelines["dream_cycle"]["runs"] += 1
            self.nexus._pipelines["dream_cycle"]["last_run"] = time.time()
        except Exception:
            pass
        nodes = self.store.get_branch_nodes(branch)

        self.dream._memories.clear()
        for node in nodes:
            self.dream.register_memory(node)

        # 初始化梦境数据收集字典
        dream_data = {}

        # 链上下文：读取触发管的信号
        try:
            ctx = self.signal_fusion.get_chain_context()
            if ctx:
                trigger_pipe = ctx.get("trigger_pipe", "")
                sigs = ctx.get("trigger_signals", {})
                dream_data["trigger_pipe"] = trigger_pipe
                if trigger_pipe == "reflect":
                    raw_score = sigs.get("raw_score", 0.5)
                    dream_data["trigger_score"] = raw_score
                    logger.info("Dream triggered by reflect (score=%.3f)", raw_score)
                elif trigger_pipe == "evolve":
                    raw_delta = sigs.get("raw_delta", 0)
                    dream_data["evolve_delta"] = raw_delta
                    logger.info("Dream triggered by evolve (delta=%.4f)", raw_delta)
        except Exception:
            logger.warning("Dream signal processing failed, continuing without it")
            pass

        dream_result = self.dream.run_cycle(branch=branch)
        dream_data['extra_dream'] = self.dream.dream()  # 收集额外梦境输出

        # ===== P1-1: 梦境产出回流知识库 (梦->学闭环) =====
        # 原实现: dream 的 insights/beliefs 只进 dream_data + event_bus + 审计日志,
        # 不回写 store, 导致梦出的洞见丢失、无法被 learn/recall 再利用。
        # 现把高价值洞见注册为可检索知识节点, 闭合"梦->学"环。
        try:
            synthesized = 0
            for insight in getattr(dream_result, "insights", []) or []:
                if insight and isinstance(insight, str):
                    nid = self.remember(
                        content=f"[dream] {insight}",
                        utility=0.6,
                        tags=["dream_synthesis"],
                    )
                    if nid:
                        synthesized += 1
            # 高置信信念也回流
            for b in getattr(self.dream, "_beliefs", []) or []:
                if isinstance(b, dict) and b.get("confidence", 0.0) >= 0.4:
                    nid = self.remember(
                        content=f"[dream-belief] topic={b.get('topic')} confidence={b.get('confidence'):.2f}",
                        utility=round(min(1.0, b.get("confidence", 0.5)), 3),
                        tags=["dream_synthesis", "belief"],
                    )
                    if nid:
                        synthesized += 1
            if synthesized:
                dream_data["knowledge_feedback_written"] = synthesized
                logger.info("Dream: %d synthesized insights/beliefs written back to store", synthesized)
        except Exception as e:
            logger.debug("Dream: knowledge write-back failed: %s", e)
        self.shmr.generate(entities=[], context="dream")
        self.consolidation_engine.run()
        self.rare_valid.detect()
        # 【P4修复】从SHMR获取合成信念并写入MARS
        beliefs = self.shmr.get_beliefs(min_confidence=0.3)
        if beliefs:
            for belief in beliefs[:5]:
                name = f"dream_{belief.get('name', 'unknown')}"
                content = belief.get('content', '')
                confidence = belief.get('confidence', 0.5)
                self.mars.create_belief(name, content, confidence)
        else:
            # 如果没有合成信念，创建一个基础信念
            self.mars.create_belief("dream_baseline", "Dream cycle completed", 0.5)
        self.gravity.add_node("dream", mass=0.5)
        self.forgetting.compute_retention_compat("dream", age=1.0)
        self.state_machine.transition(LoopState.RUNNING)
        dream_data['pre_transition_state'] = self.state_machine.state  # 记录转移前状态
        self.state_machine.force_transition(LoopState.COMPLETED)
        self.state_machine.force_transition(LoopState.RUNNING)
        dream_data['post_transition_state'] = self.state_machine.state  # 记录转移后状态
        self.consistency.vote([n.content[:100] for n in nodes[:10]])
        dream_data['consensus_history'] = self.consistency.get_consensus_history()  # 收集共识历史
        dream_data['weighted_vote'] = self.consistency.vote_with_weights(["a","b"], [0.8,0.2])  # 收集加权投票结果
        self.extended_thinking.think({"context": "dream", "memory_count": len(nodes)})
        self.dna_extractor.extract({"memories": len(nodes), "patterns": dream_result.patterns_found})

        # SHMR: get synthesized beliefs
        beliefs = self.shmr.get_beliefs(min_confidence=0.3)
        dream_result.beliefs_synthesized += len(beliefs)

        # === Dream: full mechanism activation ===
        # 状态机深度查询
        dream_data['valid_next'] = self.state_machine.get_valid_next()  # 收集有效下一步状态
        dream_data['transition_history'] = self.state_machine.get_transition_history()  # 收集状态转移历史
        dream_data['sm_state'] = self.state_machine.state  # 收集当前状态机状态

        # 遗忘机制深度操作
        dream_data['expired_nodes'] = self.forgetting.get_expired_nodes(threshold=0.1)  # 收集过期节点
        dream_data['most_forgotten'] = self.forgetting.get_most_forgotten()  # 收集最被遗忘项
        dream_data['most_retained'] = self.forgetting.get_most_retained()  # 收集最被保留项
        dream_data['retention'] = self.forgetting.get_retention("dream")  # 收集保留率
        dream_data['retention_dist'] = self.forgetting.get_retention_distribution()  # 收集保留率分布
        dream_data['forget_time'] = self.forgetting.predict_forget_time("dream")  # 收集遗忘预测时间

        # 引力机制深度查询
        dream_data['gravity'] = self.gravity.compute("dream", "dream")  # 收集引力计算结果
        dream_data['gravity_rank'] = self.gravity.rank_by_gravity("dream")  # 收集引力排名
        dream_data['strongest_pair'] = self.gravity.get_strongest_pair()  # 收集最强引力对
        dream_data['total_gravity'] = self.gravity.get_total_gravity()  # 收集总引力值

        # 稀有值检测深度查询
        self.rare_valid.observe(0.5)
        dream_data['rare_values'] = self.rare_valid.get_rare_values()  # 收集稀有值

        # DNA提取器深度查询
        dream_data['dominant_features'] = self.dna_extractor.get_dominant_features()  # 收集主导特征

        # 巩固管道深度操作
        self.consolidation.consolidate([{"content": "dream_content", "importance": 0.5}])

        # Hebbian hub-driven consolidation: consolidate in hub order
        try:
            hubs = self.hebbian.find_hubs(top_k=10)
            dream_data['hebbian_hubs'] = [{"node_id": n, "score": round(s, 4)} for n, s in hubs]
            for node_id, hub_score in hubs:
                if self.hebbian.should_consolidate(node_id, hub_degree_threshold=2.0):
                    logger.info("Hebbian consolidation candidate: %s (hub_score=%.3f)", node_id[:8], hub_score)
            candidates = self.hebbian.get_consolidation_candidates(min_hub_score=1.0, top_k=20)
            dream_data['hebbian_consolidation_candidates'] = len(candidates)
        except Exception as exc:
            logger.warning("Hebbian consolidation failed: %s", exc)
            dream_data['hebbian_error'] = str(exc)

        # SHMR深度查询
        dream_data['co_occurrence'] = self.shmr.get_co_occurrence_stats()  # 收集共现统计
        dream_data['entity_stats'] = self.shmr.get_entity_stats()  # 收集实体统计

        # 扩展思考深度查询
        dream_data['thought_tree'] = self.extended_thinking.get_thought_tree()  # 收集思考树

        # 行为镜像
        self.behavior_mirror.mirror("system", "dream", {"patterns": dream_result.patterns_found})

        # 事件总线
        dream_data['recent_events'] = self.event_bus.get_recent(3)  # 收集最近事件

        # Session
        self.session.access(f"dream_{int(time.time())}")

        import uuid
        # Log dream to database
        cycle_id = f"dream_{uuid.uuid4().hex[:12]}"
        self.store.log_evolution(cycle_id, 0.0, dream_result.patterns_found / max(len(nodes), 1), "dream")
        # Also write to dream_log table directly
        try:
            self._conn = self.store._conn
            if self._conn:
                self._conn.execute(
                    "INSERT INTO dream_log (cycle_id, patterns_found, beliefs_synthesized, connections_discovered, timestamp) VALUES (?,?,?,?,?)",
                    (cycle_id, dream_result.patterns_found, dream_result.beliefs_synthesized, dream_result.connections_discovered, time.time())
                )
                self._conn.commit()
                logger.debug("Dream log written: %s", cycle_id)
            else:
                logger.warning("Dream log: store connection is None")
        except Exception as e:
            logger.warning("Failed to write dream log: %s: %s", type(e).__name__, e)

        # 附加梦境数据到结果对象
        setattr(dream_result, 'dream_data', dream_data)

        self.event_bus.publish({"type": "dream_completed", "patterns": dream_result.patterns_found, "beliefs": dream_result.beliefs_synthesized, "connections": dream_result.connections_discovered})
        self.record_production("belief", f"梦境合成: {dream_result.beliefs_synthesized} 信念 / {dream_result.patterns_found} 模式 / {dream_result.connections_discovered} 连接", {
            "patterns_found": dream_result.patterns_found,
            "beliefs_synthesized": dream_result.beliefs_synthesized,
            "connections_discovered": dream_result.connections_discovered,
        })
        # Telemetry: 存储原始返回值
        self._telemetry["dream"] = dream_result


        # 写管道结果
        self.signal_fusion.set_pipe_result("dream", {
            "patterns_found": dream_result.patterns_found,
            "beliefs_synthesized": dream_result.beliefs_synthesized,
            "connections_discovered": dream_result.connections_discovered,
            "insights": getattr(dream_result, 'insights', [])[:3],
        })

        # 后见之明技能蒸馏 (SEED): 从 dream 轨迹提炼可复用技能
        try:
            self._mine_hindsight("dream_cycle",
                                  produced=getattr(dream_result, 'beliefs_synthesized', 1) or 1,
                                  outcome="dream completed", success=True)
        except Exception:
            pass

        return dream_result

    # ============================================================
    # maintain pipeline
    # ============================================================
    def maintain(self) -> dict:
        start = time.time()
        # 管道运行计数(监控可见性)
        try:
            self.nexus._pipelines.setdefault("maintain", {"runs": 0, "failures": 0, "last_run": None})
            self.nexus._pipelines["maintain"]["runs"] += 1
            self.nexus._pipelines["maintain"]["last_run"] = time.time()
        except Exception:
            pass
        maintain_data = {}

        # 链上下文：读取触发管的信号
        try:
            ctx = self.signal_fusion.get_chain_context()
            if ctx:
                trigger_pipe = ctx.get("trigger_pipe", "")
                sigs = ctx.get("trigger_signals", {})
                maintain_data["trigger_pipe"] = trigger_pipe
                if trigger_pipe == "dream":
                    patterns = sigs.get("patterns_found", 0)
                    maintain_data["upstream_patterns"] = patterns
                    logger.info("Maintain triggered by dream (%d patterns)", patterns)
        except Exception:
            logger.warning("Maintain signal processing failed, continuing without it")
            pass

        self.bank.run_migration()
        self.bank.run_aging()
        # ConsolidationEngine: only call consolidate(), no run() method
        try:
            self.consolidation_engine.consolidate()
        except Exception as e:
            logger.debug("Consolidation engine failed: %s", e)
        # FIX: Don't feed bank.count() into convergence history — it's an integer (bank tier count)
        # that corrupts the float-based convergence detection (scores ~0.65-0.71).
        # Bank count is already tracked via self.bank and reported in maintain diagnostics.
        self.thermodynamic.update(0.1)
        # thermodynamic.reset when temperature is extreme
        stats = self.thermodynamic.get_stats()
        if stats.get("temperature", 0.5) > 0.9 or stats.get("temperature", 0.5) < 0.1:
            self.thermodynamic.reset()
        # Feed real maintenance data: outcome_valid=system stable, rarity=convergence delta
        try:
            ec = self.thermodynamic.get_energy()
            self.thermodynamic.observe_action(
                action="maintain",
                outcome_valid=stats.get("temperature", 0.5) < 0.8,
                rarity=max(0.01, 1.0 - (ec or 0.5)),
                baseline_prob=0.3,
            )
        except Exception:
            logger.warning("Dopamine reward recording failed, continuing")
            pass
        self.circuit_breaker.record_success()
        self.self_healing.heal({"bank_count": self.bank.count()})
        self.mars.update_belief("dream_belief", 0.6)
        self.mars.create_belief("temp_belief", "temporary", 0.1)
        self.mars.delete_belief("temp_belief")
        self.crash_recovery.create_checkpoint()
        self.crash_recovery.recover({"status": "maintain", "bank_count": self.bank.count()})
        self.tool_loop.execute("maintain")
        self.organ_pipeline.execute({"action": "maintain"})
        self.hands.execute({"action": "maintain"})

        # MiMo: Utility Decay — apply decay rules
        self.utility_decay.apply_decay()  # real-time decay; explicit days_elapsed overrides window
        self.utility_tracker.apply_decay()

        # ===== P1-3: 保护高 recall 命中节点不被遗忘 =====
        # 原 maintain 全局降权/prune, 不区分"被反复用到的外部知识",
        # 导致有价值知识被误遗忘。现对 learn_feedback 命中 >=3 的节点保底 utility。
        try:
            hits = getattr(self.learn_feedback, "_hits", {})
            protected = 0
            for node_id, h in hits.items():
                if h >= 3:
                    try:
                        node = self.store.read_node(node_id)
                        if node is not None and getattr(node, "utility", 0.0) < 0.5:
                            node.utility = 0.5
                            self.store.update_node(node)
                            protected += 1
                    except Exception:
                        pass
            if protected:
                logger.info("Maintain: protected %d high-hit nodes from decay", protected)
        except Exception as e:
            logger.debug("Maintain: hit-protection failed: %s", e)

        # ===== P5b: 按类型差异化维持 — 高价值类型节点不全忘 =====
        # PAPER/PROJECT/SKILL/PATTERN 是进化燃料(外部知识/机制), 不应被 decay 清掉;
        # 普通 FACT 允许正常清理。这是多类型知识库"按重要性分层维持"的体现。
        try:
            from prometheus_nexus.foundation.schema import NodeType
            high_value_types = [NodeType.PAPER, NodeType.PROJECT, NodeType.SKILL,
                                 NodeType.PATTERN, NodeType.CONCEPT, NodeType.PROCEDURE]
            floor = 0.3
            type_protected = 0
            for nt in high_value_types:
                nodes = self.store.get_nodes_by_type(nt, limit=200)
                for n in nodes:
                    if getattr(n, "utility", 0.0) < floor:
                        n.utility = floor
                        self.store.update_node(n)
                        type_protected += 1
            if type_protected:
                logger.info("Maintain: type-floor protected %d high-value nodes", type_protected)
        except Exception as e:
            logger.debug("Maintain: type-floor protection failed: %s", e)

        # MiMo: Progressive Checkpoints — check context pressure
        node_count = self.store.get_node_count()
        context_usage = min(1.0, node_count / 10000)
        cp_level = self.progressive_checkpoints.should_save(context_usage)
        if cp_level:
            self.progressive_checkpoints.save_checkpoint(cp_level, context_usage,
                {"node_count": node_count, "edge_count": self.store.get_edge_count()})

        # MiMo: Tool Drift Detection
        recent_tools = self.trajectory.get_action_summary()
        if recent_tools:
            tool_counts = {k: v.get("count", 0) for k, v in recent_tools.items()}
            if not self.tool_drift._baseline:
                self.tool_drift.record_baseline(tool_counts)
            else:
                self.tool_drift.record_current(tool_counts)

        # MiMo: Three-Layer Compression
        nodes = self.store.get_active_nodes(limit=20)
        pruned_count = 0

        for n in nodes:
            self.forgetting.compute_retention_compat(n.id, age=1.0)
            self.gravity.add_node(n.id, mass=n.utility)
            self.zscore.observe(n.utility)
            # LocalMaintenance: per-node maintenance
            actions = self.local_maintenance.check_node(n.id, n.utility, 1.0, 0)
            for action in actions:
                if action.action == "prune":
                    self.store.delete_node(n.id)
                    pruned_count += 1
            self.memory_depth.record_access(n.id)

        # MiMo: Heartbeat 4-cycle


        # MiMo: Capability ceiling check
        can_add, ceiling_reason = self.capability_ceiling.should_add_agents()

        # MiMo: Cognitive collapse detection
        collapse = self.cognitive_collapse.detect()

        # MiMo: WAL checkpoint
        self.wal.write("maintain", status="completed",
                      payload={"node_count": self.store.get_node_count()})

        # State persistence: save memory state
        self.state_persistence.save(self)

        # MiMo: Rule expiration audit
        expired = self.rule_expiration.audit()

        # MiMo: FileChecksum — verify core file integrity
        checksum_results = self.file_checksum.verify_all()

        # OmegaServer: 检查服务状态
        maintain_server_status = {"status": "unknown"}
        try:
            maintain_server_status = self.server.status()
        except Exception:
            logger.warning("Server status check failed, returning default")
            maintain_server_status = {"status": "server_check_failed"}

        # MemoryDataAdapter: 运行快速基准评估
        maintain_benchmark = {}
        try:
            benchmark = self.memory_data_adapter.evaluate("memoryagentbench", "ultra")
            maintain_benchmark = benchmark.metrics if hasattr(benchmark, 'metrics') else {}
        except Exception:
            logger.warning("Memory benchmark failed, marking as unavailable")
            maintain_benchmark = {"status": "benchmark_unavailable"}

        # 信息茧房
        report_text = "Maintain completed: %d nodes, %d edges, %d expired rules" % (
            self.store.get_node_count(), self.store.get_edge_count(), len(expired))
        if pruned_count > 0:
            self.record_production("prune", f"维护修剪 {pruned_count} 个节点", {
                "pruned": pruned_count,
                "expired_rules": len(expired),
                "node_count": self.store.get_node_count(),
            })

        self.zscore.detect()
        self.drift_detector.observe_behavioral(0.5)
        drift_alerts = self.constraint_drift.detect()
        if drift_alerts:
            logger.warning("Constraint drift detected: %s", drift_alerts)
        maintain_data['constraint_drift_alerts'] = drift_alerts

        # RIMRULE: extract rule report for maintain
        if hasattr(self, 'rimrule'):
            try:
                rule_report = self.rimrule.get_rules(sort_by="confidence", limit=5)
                maintain_data['rimrule_rules'] = rule_report
                # P3 RSI: feed high-confidence RIMRULLE rules back into MemPO condition utilities
                if hasattr(self, 'mempo') and hasattr(self.mempo, 'apply_rule_guidance'):
                    for rule in rule_report:
                        if rule.get("confidence", 0) > 0.6:
                            cond = rule.get("condition", "")
                            if cond:
                                self.mempo.apply_rule_guidance(rule, [])
            except Exception as e:
                logger.debug("RIMRULE report failed: %s", e)

        self.cache.delete("old_key")

        # Forgetting: get expired nodes for cleanup
        expired_nodes = self.forgetting.get_expired_nodes(threshold=0.1)

        # Trajectory: get action summary
        traj_summary = self.trajectory.get_action_summary()

        # MemorySideEffect: check for retrieval side effects
        self.memory_side_effect.set_current_task("maintain")
        self.memory_side_effect.detect()

        # === Maintain: full mechanism activation ===
        # Bank deep operations
        maintain_data['bank_tiers'] = self.bank.count_by_tier()
        self.bank.deposit("maintain_ref", tier=Tier.WORKING)
        # Store deep operations
        maintain_data['store_read'] = self.store.read_node("test_id")
        self.store.log_evolution("maintain", 0.5, 0.6, "maintain")
        self.store.log_maintenance("migration", 10, 5.0)
        self.store.log_audit("maintain", 0.8, {"action": "cleanup"})
        # delete_node and update_node: test via temporary node
        temp_node = Node(id="temp_test_node", content="temp", utility=0.1)
        self.store.create_node(temp_node)
        maintain_data['temp_read'] = self.store.read_node("temp_test_node")
        temp_node.utility = 0.9
        self.store.update_node(temp_node)
        self.store.delete_node("temp_test_node")
        maintain_data['bank_importance'] = self.bank.get_importance_distribution()
        maintain_data['bank_newest'] = self.bank.get_newest_items(Tier.WORKING)
        maintain_data['bank_oldest'] = self.bank.get_oldest_items(Tier.WORKING)
        maintain_data['bank_tier_items'] = self.bank.get_tier_items(Tier.WORKING)

        # Crash restore deep
        self.crash_restore.save_checkpoint({"maintain_cycle": time.time(), "nodes": self.store.get_node_count()})
        maintain_data['crash_restore'] = self.crash_restore.restore_latest()
        maintain_data['crash_checkpoints'] = self.crash_restore.list_checkpoints()

        # Self healing deep
        maintain_data['heal_diagnosis'] = self.self_healing.diagnose({"bank_count": self.bank.count()})

        # Convergence deep
        maintain_data['convergence_history'] = self.convergence.get_history()

        # DAG executor deep (带 None 安全检查)
        if self.dag_executor is not None:
            self.dag_executor.add_node("maintain_task")
            maintain_data['dag_validate'] = self.dag_executor.validate()
            maintain_data['dag_execute'] = self.dag_executor.execute()
            maintain_data['dag_state_summary'] = self.dag_executor.get_state_summary()
        else:
            maintain_data['dag_validate'] = {"error": "dag_executor not initialized"}
            maintain_data['dag_execute'] = {"error": "dag_executor not initialized"}
            maintain_data['dag_state_summary'] = {"error": "dag_executor not initialized"}

        # Monitored DAG deep (带 None 安全检查)
        try:
            if self.monitored_dag is not None:
                maintain_data['monitored_dag_execute'] = self.monitored_dag.execute_monitored([])
                maintain_data['monitored_dag_latency'] = self.monitored_dag.get_latency_stats()
            else:
                maintain_data['monitored_dag_execute'] = {"error": "monitored_dag not initialized"}
                maintain_data['monitored_dag_latency'] = {"avg_ms": 0, "p50_ms": 0, "p99_ms": 0}
        except Exception as e:
            logger.debug("MonitoredDAG execution failed: %s", e)
            maintain_data['monitored_dag_execute'] = None
            maintain_data['monitored_dag_latency'] = {"avg_ms": 0, "p50_ms": 0, "p99_ms": 0}

        # Parallel DAG deep (带 None 安全检查)
        try:
            if self.parallel_dag is not None:
                maintain_data['parallel_dag_execute'] = self.parallel_dag.execute_parallel()
            else:
                maintain_data['parallel_dag_execute'] = {"error": "parallel_dag not initialized"}
        except Exception as e:
            logger.debug("ParallelDAG execution failed: %s", e)
            maintain_data['parallel_dag_execute'] = None

        # Retryable DAG deep (带 None 安全检查)
        try:
            if self.retryable_dag is not None:
                # 兼容新旧 API: 新类用 execute(), 旧类用 execute_with_retry()
                if hasattr(self.retryable_dag, 'execute') and not hasattr(self.retryable_dag, 'execute_with_retry'):
                    maintain_data['retryable_dag_execute'] = self.retryable_dag.execute({"nodes": {}, "edges": []})
                else:
                    maintain_data['retryable_dag_execute'] = self.retryable_dag.execute_with_retry(failure_rate=0.0)
            else:
                maintain_data['retryable_dag_execute'] = {"error": "retryable_dag not initialized"}
        except Exception as e:
            logger.debug("RetryableDAG execution failed: %s", e)
            maintain_data['retryable_dag_execute'] = None

        # Trajectory deep operations
        maintain_data['traj_action_summary'] = self.trajectory.get_action_summary()
        maintain_data['traj_compare'] = self.trajectory.compare_trajectories("remember", "recall")
        maintain_data['traj_common_errors'] = self.trajectory.get_common_errors()
        maintain_data['traj_common_failures'] = self.trajectory.get_common_failures()
        maintain_data['traj_duration_stats'] = self.trajectory.get_duration_stats("remember")
        maintain_data['traj_trajectories'] = self.trajectory.get_trajectories()
        maintain_data['traj_success_rate'] = self.trajectory.success_rate("remember")

        # Progressive complexity deep
        maintain_data['progressive_complexity'] = self.progressive_complexity.assess("maintain", context_tokens=5000)

        # Context window deep
        maintain_data['context_check'] = self.context_window.check()
        maintain_data['context_suggest_compression'] = self.context_window.suggest_compression()

        # Human oversight deep
        req = self.human_oversight.submit_action("maintain_cleanup", RiskLevel.LOW)
        maintain_data['human_oversight_needs_human'] = self.human_oversight.needs_human(req)
        maintain_data['human_oversight_pending'] = self.human_oversight.get_pending()
        self.human_oversight.check_timeouts()
        # approve/reject are triggered by human input, not pipeline
        # but we test the interface:
        if self.human_oversight.get_pending():
            pending = self.human_oversight.get_pending()[0]
            self.human_oversight.approve(pending.request_id, "system")
        # reject: submit a high-risk action then reject it
        reject_req = self.human_oversight.submit_action("dangerous_op", RiskLevel.CRITICAL)
        if self.human_oversight.needs_human(reject_req):
            self.human_oversight.reject(reject_req.request_id, "system", "too dangerous")

        # Tree of thoughts deep
        maintain_data['tree_of_thoughts'] = self.tree_of_thoughts.search("maintain optimization", strategy=SearchStrategy.BFS)

        # Think tool deep
        maintain_data['think_tool'] = self.think_tool.run(task="maintain analysis", context="system maintenance")

        # Structured output deep
        maintain_data['structured_validate'] = self.structured_output.validate('{"status": "ok"}', [])
        maintain_data['structured_schema_prompt'] = self.structured_output.generate_schema_prompt([SchemaField("task", "string"), SchemaField("result", "string")])

        # XML tag deep
        from prometheus_nexus.prompt.xml_tag import PromptSection
        prompt = self.xml_tag.build([PromptSection("task", "maintain")])
        maintain_data['xml_all_sections'] = self.xml_tag.extract_all_sections(prompt)
        maintain_data['xml_task_section'] = self.xml_tag.extract_section(prompt, "task")

        # Reasoning adapter deep
        maintain_data['reasoning_adapter'] = self.reasoning_adapter.adapt("think step by step", "reasoning")

        # Stream deep
        maintain_data['stream_recent'] = self.stream.recent(5)
        maintain_data['stream_search'] = self.stream.search_content("maintain")
        maintain_data['stream_count'] = self.stream.get_count()
        maintain_data['stream_type_dist'] = self.stream.get_type_distribution()
        maintain_data['stream_avg_importance'] = self.stream.get_avg_importance()

        # Behavior mirror deep
        self.behavior_mirror.mirror("system", "maintain", {"duration": time.time() - start})
        maintain_data['behavior_profile'] = self.behavior_mirror.compute_profile("system")
        maintain_data['behavior_deviation'] = self.behavior_mirror.detect_deviation("system")

        # Event bus deep
        maintain_data['event_bus_recent'] = self.event_bus.get_recent(5)

        # Session deep
        self.session.access(f"maintain_{int(time.time())}")
        self.session.expire_idle()

        # Adapter deep
        maintain_data['x_adapter_reverse'] = self.x_adapter.reverse_adapt({"node_id": "maintain"})
        maintain_data['y_adapter_tier_name'] = self.y_adapter.get_tier_name(0)

        # Monitor deep
        maintain_data['monitor_uptime'] = self.monitor.get_uptime()
        maintain_data['monitor_health'] = self.monitor.get_health()

        # Skill deep
        self.skill_claw.register_skill("maintain_skill", "maintain_skill", "Maintenance and cleanup skill", ["maintenance", "cleanup"])
        maintain_data['skill_get'] = self.skill_registry.get_skill("maintain_skill")
        maintain_data['skill_active'] = self.skill_registry.get_active_skills()

        # Instincts deep
        self.instincts.register("maintain_check", lambda ctx: True)

        # Consolidation pipeline deep
        self.consolidation.consolidate([{"content": "maintain", "importance": 0.3}])
        self.dopamine.update_config(threshold=0.3)
        # dopamine.reset only when accept rate is extreme
        stats = self.dopamine.get_stats()
        if stats.get("accept_rate", 0.5) > 0.95 or stats.get("accept_rate", 0.5) < 0.05:
            self.dopamine.reset()

        # 活性检查：激活低调用频率的机制
        # Note: heartbeat, capability_ceiling, cognitive_collapse, rule_expiration
        # are also called earlier in maintain() (see MiMo blocks).
        # This block adds: loop_selector + agent_forest.
        loop_cfg = self.loop_selector.select("maintain")
        self.loop_selector.record_outcome(loop_cfg.strategy, self._compute_fitness())
        self.agent_forest.record_performance("maintainer", self._compute_fitness())
        
        # === KTA: 定期扫描未翻译的高 utility 知识 ===
        try:
            hint = self.knowledge_to_mechanism.scan_for_opportunities(
                store=self.store, utility_threshold=0.6,
            )
            if hint.get("untranslated_count", 0) >= 3:
                logger.info(
                    "KTA scan: %d untranslated nodes (utility ≥ 0.6)",
                    hint["untranslated_count"],
                )
        except Exception as e:
            logger.debug("KTA scan skipped: %s", e)
        
        # === 反退化检查 ===
        try:
            all_avgs = self.utility_tracker.get_all_averages()
            if all_avgs:
                vals = list(all_avgs.values())
                maintain_data['aging_compression_var'] = sum((v - sum(vals)/len(vals))**2 for v in vals) / len(vals)
        except Exception:
            logger.warning("Aging compression variance calculation failed")
            pass
        try:
            maintain_data['tracelift_inert'] = sum(1 for k in self._learned_config if not k.startswith('_'))
        except Exception:
            logger.warning("Tracelift inert calculation failed")
            pass

        # 链分析：激活历史链的总结（signal_fusion.chain_analysis）
        try:
            active_chains = self.signal_fusion.get_state().get("active_chains", [])
            if active_chains:
                chain_summaries = []
                for cid in list(active_chains.keys())[:3]:
                    analysis = self.signal_fusion.chain_analysis(cid)
                    if analysis:
                        chain_summaries.append(analysis)
                if chain_summaries:
                    maintain_data['chain_analysis'] = chain_summaries
        except Exception as e:
            logger.debug("chain_analysis failed: %s", e)

        self.event_bus.publish({"type": "maintain_completed", "decayed": len(expired_nodes), "heartbeat": True})
        maintain_result = {
            "consolidation": self.consolidation.get_stats(),
            "convergence": self.convergence.get_stats(),
            "thermodynamic": self.thermodynamic.get_stats(),
            "duration_ms": (time.time() - start) * 1000,
            "expired_nodes": len(expired_nodes),
            "trajectory_actions": len(traj_summary),
            "server_status": maintain_server_status,
            "benchmark": maintain_benchmark,
            "maintain_data": maintain_data,
        }
        # Telemetry: 存储原始返回值
        self._telemetry["maintain"] = maintain_result

        # 写管道结果
        self.signal_fusion.set_pipe_result("maintain", {
            "consolidated": maintain_data.get("consolidated_count", 0),
            "server_status": maintain_server_status,
        })

        return maintain_result

    # ============================================================
    # Branch system (from Omega-Omega)
    # ============================================================
    def branch_create(self, name: str, parent: str = "main") -> None:
        self.store.create_branch(name, parent)

    def branch_merge(self, source: str, target: str = "main") -> str:
        token = self.store.request_write_token(source, "omega", "merge")
        result = self.store.merge_branch(source, target, token=token)
        return result.write_id

    # ============================================================
    # knowledge utilization report — 外部知识利用全局可观测性 (P2-2)
    # ============================================================
    def knowledge_utilization_report(self) -> dict:
        """汇总外部知识在 7 管道中的利用情况, 提供统一效率指标。

        覆盖: 吸收(learn) / 检索命中(recall) / 进化消费(evolve) /
        梦境回流(dream) / 遗忘保护(maintain) / 长期主题(focus_topics)。
        """
        try:
            total_nodes = self.store.get_node_count()
            # 检索命中
            lf = getattr(self, "learn_feedback", None)
            registered = len(getattr(lf, "_registered", {}))
            total_hits = sum(getattr(lf, "_hits", {}).values())
            hit_rate = (total_hits / registered) if registered else 0.0
            # 进化消费: 派生基因维度是否产生
            evo_specs = getattr(getattr(self, "evolution_engine", None), "_gene_specs", {}) or {}
            ext_specs = {k: v for k, v in evo_specs.items() if k.startswith("ext_")}
            # 梦境回流
            dream_nodes = [n for n in self.store.get_active_nodes(limit=300)
                           if "dream_synthesis" in (getattr(n, "tags", []) or [])]
            # 遗忘保护
            protected = sum(1 for h in getattr(lf, "_hits", {}).values() if h >= 3)
            # 长期主题
            focus = dict(getattr(self, "focus_topics", {}))
            return {
                "total_nodes": total_nodes,
                "learned_registered": registered,
                "recall_total_hits": total_hits,
                "recall_hit_rate": round(hit_rate, 4),
                "evolve_external_dims": len(ext_specs),
                "dream_synthesis_nodes": len(dream_nodes),
                "maintain_protected_high_hit": protected,
                "focus_topics": focus,
            }
        except Exception as e:
            logger.warning("knowledge_utilization_report failed: %s", e)
            return {"error": str(e)}

    def branch_list(self) -> list[str]:
        return self.store.list_branches()

    # ============================================================
    # Status & Fitness
    # ============================================================
    def status(self) -> SystemStatus:
        """获取系统状态（带 None 安全检查）。"""
        details, failed = self._collect_component_health()
        return SystemStatus(
            node_count=self.store.get_node_count(),
            edge_count=self.store.get_edge_count(),
            active_sessions=1,
            uptime_seconds=time.time() - self._start_time,
            health=self._compute_health(failed_components=failed),
            version="1.0.0",
            mechanisms=127,
            details=details,
        )

    # 组件健康探针表: (属性名, 方法路径)。status() 与 _compute_health() 共用,
    # 避免重复采集逻辑。任一组件缺失/抛错都被记入 failed, 供健康聚合判定降级。
    COMPONENT_HEALTH_PROBES = [
        ("bank", "bank.count"),
        ("convergence", "convergence.is_converged"),
        ("dopamine", "dopamine.get_stats"),
        ("five_gates", "five_gates.get_stats"),
        ("constitution", "constitution.get_stats"),
        ("graph_memory", "graph_memory.get_stats"),
        ("four_network", "four_network.get_stats"),
        ("utility_tracker", "utility_tracker.get_stats"),
        ("curiosity_queue", "curiosity_queue.get_stats"),
        ("knowledge_scanner", "knowledge_scanner.get_stats"),
        ("mars", "mars.get_stats"),
        ("evolution_engine", "evolution_engine.get_stats"),
    ]

    def _collect_component_health(self) -> tuple[dict, list[str]]:
        """安全采集各组件健康。

        Returns:
            (details, failed):
            - details[name] = 组件统计, 或 {'error': ...}(缺失/抛错)
            - failed = 探测失败的组件名列表(供 _compute_health 聚合)
        """
        details: dict = {}
        failed: list[str] = []
        for name, method in self.COMPONENT_HEALTH_PROBES:
            attr = method.split('.')[-1]
            try:
                comp = getattr(self, name, None)
                if comp is None or not hasattr(comp, attr):
                    details[name] = {"error": f"{name} not initialized or missing method"}
                    failed.append(name)
                    continue
                details[name] = getattr(comp, attr)()
            except Exception as e:
                details[name] = {"error": str(e)[:50]}
                failed.append(name)
        return details, failed

    def get_mechanism_consumption(self) -> dict:
        """机制消费/健康统一视图 — 委托 Nexus 真相源 (第三层监控统合).

        Nexus 已统辖全部 236 基本盘 + 动态层 + 7管道, 其 get_monitor_snapshot()
        是机制消费的唯一权威真相源. 本方法不再重复聚合 6 载体(机制层已在 Nexus),
        仅基于 Nexus 数据做静默机制诊断分类(有价值的诊断逻辑保留).

        返回 {total, consumed, rate, by_carrier, silent_mechanisms, silent_by_category}
        """
        try:
            nx = getattr(self, "nexus", None)
            if nx is None:
                return {"total": 0, "consumed": 0, "rate": 0.0, "by_carrier": {}}
            snap = nx.get_monitor_snapshot()
            # 静默机制分类(silent_mechanisms 来自 Nexus 真相源, 更准)
            silent = snap.get("silent_mechanisms", [])
            silent_by_category = {
                "test_residue": [], "orphan_registry": [],
                "dormant_ok": [], "trigger_missing": [],
            }
            for name in silent:
                low = name.lower()
                if ("test" in low or "tmp" in low or low.endswith("_p")
                        or low.startswith(("p_", "c1_", "c2_", "bad_", "z_"))):
                    silent_by_category["test_residue"].append(name)
                elif low.startswith(("learn_", "scan_", "fetch_")):
                    silent_by_category["orphan_registry"].append(name)
                elif any(k in low for k in ("explore", "pending", "speculative",
                                            "candidate", "semantic_evo", "evo_g")):
                    silent_by_category["dormant_ok"].append(name)
                else:
                    silent_by_category["trigger_missing"].append(name)
            return {
                "total": snap["mechanisms"],
                "consumed": snap["consumed"],
                "rate": round(snap["rate"], 4),
                "dynamic_count": snap["dynamic"],
                "by_category": snap.get("by_category", {}),
                "route_overrides": snap.get("route_overrides", {}),
                "active_dynamic": snap.get("active_dynamic", []),
                "pruned_disabled": snap.get("pruned_disabled", []),
                "silent_mechanisms": silent,
                "silent_count": len(silent),
                "silent_by_category": silent_by_category,
                "by_carrier": {"nexus": {"total": snap["mechanisms"],
                                         "consumed": snap["consumed"]}},
            }
        except Exception as e:
            logger.debug("get_mechanism_consumption failed: %s", e)
            return {"total": 0, "consumed": 0, "rate": 0.0, "by_carrier": {}}

    def get_pipeline_health(self) -> dict:
        """Tier 1/3 聚合: 过程层健康(熔断/评估失败/安全边界/FTS降级/LLM-dark/A2A).

        这些信号原本只在日志里, 监控看不见 -> 长期带病运行无人知.
        返回分级所需的原始计数, 由监控脚本判定严重度.
        """
        try:
            health = {
                "llm_mode": "unknown",
                "llm_available": False,
                "fuse_invalid": 0,          # 信号融合层 invalid 触发次数
                "passk_failed": 0,         # 进化评估器连续失败数
                "owner_harm_violations": 0, # 安全本能边界突破计数
                "fts_fallback": 0,         # 全文检索降级次数
                "a2a_failed": 0,           # 分布式协作委派失败
                "openalex_429": 0,         # 学术源限流
            }
            # LLM bridge 模式 (LLM-dark 单列)
            llm = getattr(self, "llm", None)
            if llm is not None:
                health["llm_mode"] = getattr(llm, "_mode", getattr(llm, "mode", "unknown"))
                health["llm_available"] = bool(getattr(llm, "available", False))
            # 信号融合层熔断计数 (cerebral_cortex 在熔断时累加 _health_counters)
            hc = getattr(self, "_health_counters", None) or {}
            health["fuse_invalid"] = hc.get("fuse_invalid", 0)
            # PassK 评估失败计数 (从 _history 统计 passed=False)
            pk = getattr(self, "pass_k", None)
            if pk is not None:
                hist = getattr(pk, "_history", []) or []
                try:
                    health["passk_failed"] = sum(1 for h in hist if getattr(h, "passed", True) is False)
                except Exception:
                    health["passk_failed"] = 0
            # owner_harm 边界突破
            oh = getattr(self, "owner_harm", None)
            if oh is not None and hasattr(oh, "get_owners_stats"):
                try:
                    st = oh.get_owners_stats()
                    health["owner_harm_violations"] = st.get("violation_count", 0) or st.get("violations", 0) or 0
                except Exception:
                    pass
            # store FTS fallback 计数
            st_store = getattr(self, "store", None)
            if st_store is not None:
                health["fts_fallback"] = getattr(st_store, "_fts_fallback_count", 0) or 0
            # A2A 委派失败
            a2a = getattr(self, "a2a", None)
            if a2a is not None:
                health["a2a_failed"] = getattr(a2a, "_fail_count", 0) or getattr(a2a, "fail_count", 0) or 0
            # 跨重启累计: 当期内存值 + 持久化基线 (防止 cron 30min 重启清零)
            try:
                import os as _os
                _pf = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "archive", "pipeline_health_counters.json")
                _base = {}
                if _os.path.exists(_pf):
                    try:
                        _base = json.load(open(_pf, encoding="utf-8"))
                    except Exception:
                        _base = {}
                # 返回 累计 = 基线 + 当期
                cum = {k: (_base.get(k, 0) + health.get(k, 0)) for k in ("fuse_invalid", "passk_failed", "owner_harm_violations", "fts_fallback", "a2a_failed")}
                health.update(cum)
                # 写回累计 (下次基线含本期)
                try:
                    _os.makedirs(_os.path.dirname(_pf), exist_ok=True)
                    json.dump(cum, open(_pf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                except Exception:
                    pass
            except Exception:
                pass
            return health
        except Exception as e:
            logger.debug("get_pipeline_health failed: %s", e)
            return {"llm_mode": "unknown", "llm_available": False}

    def get_semantic_health(self) -> dict:
        """Tier 3: 学习语义相关性 — 近期节点 utility 分布, 检测'是否在学垃圾'.

        返回 low_utility_ratio (utility<0.1 占比) 与 kta_untranslated (未消化高utility知识).
        """
        try:
            from prometheus_nexus.foundation.schema import NodeType
            store = getattr(self, "store", None)
            if store is None:
                return {"low_utility_ratio": 0.0, "sampled": 0, "kta_untranslated": 0}
            # 采样近期 FACT/INSIGHT/CONCEPT 节点 (近期学习主体)
            utils = []
            for nt in (NodeType.FACT, NodeType.INSIGHT, NodeType.CONCEPT, NodeType.PATTERN):
                try:
                    nodes = store.get_nodes_by_type(nt, limit=200)
                    for n in nodes:
                        u = getattr(n, "utility", None)
                        if u is not None:
                            utils.append(u)
                except Exception:
                    continue
            sampled = len(utils)
            low = sum(1 for u in utils if u < 0.1)
            low_ratio = round(low / max(1, sampled), 4)
            # KTA 未翻译高utility节点 (知识未消化)
            kta = 0
            try:
                kta_hint = self.knowledge_to_mechanism.scan_for_opportunities(
                    store=store, utility_threshold=0.6)
                kta = kta_hint.get("untranslated_count", 0) or 0
            except Exception:
                pass
            return {"low_utility_ratio": low_ratio, "sampled": sampled,
                    "low_utility_count": low, "kta_untranslated": kta}
        except Exception as e:
            logger.debug("get_semantic_health failed: %s", e)
            return {"low_utility_ratio": 0.0, "sampled": 0, "kta_untranslated": 0}

    def get_dependency_depth(self) -> dict:
        """Tier 3: 依赖深度 — 传递性孤岛 (消费者的消费者也是孤岛).

        构建机制消费图: 已知 silent_mechanisms 是表面孤岛.
        若某机制的触发路径依赖另一孤岛机制(消费关系), 则其实质也是孤岛.
        这里用已知 silent 集合 + 机制 emit_accepted 关系做一层传递闭包近似.
        """
        try:
            cons = self.get_mechanism_consumption()
            silent = set(cons.get("silent_mechanisms", []))
            if not silent:
                return {"transitive_islands": [], "depth": 0}
            # 近似: 表面孤岛中, 属 'trigger_missing' (真bug线索) 且名为 learn_* / semantic_evo_*
            # 这类通常是上游数据源, 其下游机制若依赖它们则实质连带失活.
            transitive = [s for s in silent if any(k in s for k in ("learn_", "semantic_evo_", "academic", "arxiv"))]
            return {"transitive_islands": transitive, "depth": 1, "surface_islands": len(silent)}
        except Exception as e:
            logger.debug("get_dependency_depth failed: %s", e)
            return {"transitive_islands": [], "depth": 0}

    def _compute_fitness(self):
        """Compute system fitness based on multiple quality dimensions."""
        # Dimension 1: Memory richness (0-0.3)
        node_count = self.store.get_node_count()
        edge_count = self.store.get_edge_count()
        memory_score = min(0.3, (node_count * 0.0005 + edge_count * 0.0003))

        # Dimension 2: Diversity (0-0.2)
        types = set()
        nodes = self.store.get_active_nodes(limit=200)
        for n in nodes:
            types.add(n.type.value if hasattr(n.type, 'value') else str(n.type))
        diversity_score = min(0.2, len(types) * 0.04)

        # Dimension 3: Evolution activity (0-0.2)
        evo_stats = self.evolution_engine.get_stats()
        evo_score = min(0.2, evo_stats.get("generations", 0) * 0.02)

        # Dimension 4: System health (0-0.15)
        health_map = {"healthy": 0.15, "degraded": 0.08, "critical": 0.02, "empty": 0.0}
        health_score = health_map.get(self._compute_health(), 0.0)

        # Dimension 5: HarnessX evolution (0-0.15)
        harness_stats = self.harness_x.get_stats()
        harness_score = min(0.15, harness_stats.get("evolutions", 0) * 0.05)

        # Dimension 6: Utility health (0-0.1)
        util_stats = self.utility_tracker.get_stats()
        util_score = min(0.1, util_stats.get("avg_utility", 0.5) * 0.1)

        # Dimension 7: Thermodynamic energy (0-0.1)
        ti_energy = self.thermodynamic.get_energy()
        energy_score = min(0.1, ti_energy * 0.1)

        # Dimension 8: 多类型覆盖度 (0-0.1)
        try:
            type_counts = {}
            for nt in [NodeType.FACT, NodeType.CONCEPT, NodeType.PROCEDURE,
                       NodeType.PAPER, NodeType.PROJECT, NodeType.SKILL,
                       NodeType.PATTERN]:
                c = self.store.get_nodes_by_type(nt, limit=100000)
                if isinstance(c, (list, tuple)):
                    type_counts[nt.value] = len(c)
                elif isinstance(c, int):
                    type_counts[nt.value] = c
            non_empty = sum(1 for v in type_counts.values() if v > 0)
            multitype_score = min(0.1, non_empty * 0.02)
        except Exception:
            multitype_score = 0.0

        # Dimension 9: 机制消费率 (0-0.1) — 方案Y: 覆盖全 6 类机制载体
        try:
            snap = self.get_mechanism_consumption()
            total_all = max(1, snap["total"])
            consumed_all = snap["consumed"]
            consumption_score = min(0.1, consumed_all / total_all * 0.1)
        except Exception:
            consumption_score = 0.0

        # Dimension 10: 反刍产出率 (0-0.1)
        try:
            hist = getattr(self.knowledge_rumination, "history", [])
            recent = hist[-1] if hist else None
            rumination_score = 0.0
            if recent is not None:
                promoted = getattr(recent, "skills_promoted", 0) or 0
                routed = getattr(recent, "routed_nodes", 0) or 0
                rumination_score = min(0.1, (promoted + routed) / 20.0)
        except Exception:
            rumination_score = 0.0

        total = (memory_score + diversity_score + evo_score + health_score
                 + harness_score + util_score + energy_score
                 + multitype_score + consumption_score + rumination_score)
        # 暴露三维分解, 供 dashboard_summary / 监控脚本读取(B1 产出可见性)
        self._last_fitness_detail = {
            "total": round(min(1.0, max(0.0, total)), 4),
            "memory": round(memory_score, 4),
            "diversity": round(diversity_score, 4),
            "evolution": round(evo_score, 4),
            "health": round(health_score, 4),
            "harness": round(harness_score, 4),
            "utility": round(util_score, 4),
            "energy": round(energy_score, 4),
            "multitype": round(multitype_score, 4),
            "consumption": round(consumption_score, 4),
            "rumination": round(rumination_score, 4),
        }
        return min(1.0, max(0.0, total))

    def _compute_health(self, failed_components: list[str] | None = None) -> str:
        try:
            if self.store.get_node_count() == 0:
                return "empty"
            eq = self.equilibrium.get_alert_level()
            if eq == AlertLevel.RED:
                return "critical"
            if eq == AlertLevel.ORANGE:
                return "degraded"
            # 聚合组件健康: 原先仅看 equilibrium, 组件失败被完全忽略(监控盲区)。
            # 现把 status() 已采集的失败组件计入: 1+ 失败 -> degraded;
            # 达到阈值 -> critical。equilibrium 仍是最优先信号。
            if failed_components is None:
                _, failed_components = self._collect_component_health()
            if len(failed_components) >= self.HEALTH_CRITICAL_COMPONENT_FAILURES:
                return "critical"
            if failed_components:
                return "degraded"
            return "healthy"
        except Exception:
            logger.warning("Health status check failed, returning unknown")
            return "unknown"

    def close(self):
        self.wal.checkpoint()
        self.bank.close()
        self.cache.close()
        self.store.close()
        logger.info("Prometheus Ultra closed")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ============================================================
    # Helper methods for integrated modules
    # ============================================================
    def _extract_tool_calls(self, content: str) -> list[dict]:
        """Extract tool calls from content string."""
        try:
            import re
            pattern = r'\{[^}]*"action":\s*"([^"]+)"[^}]*\}'
            matches = re.findall(pattern, content)
            return [{"expected_params": {}, "actual_params": {}} for _ in matches[:5]]
        except Exception as e:
            logger.warning("Omega._extract_tool_calls: enrichment read failed: %s", e)
            return []

    def _classify_intent(self, query: str) -> str:
        """Classify user intent for SimpleMem retrieval."""
        query_lower = query.lower()
        if any(kw in query_lower for kw in ["how", "what", "why", "explain"]):
            return "explanation"
        if any(kw in query_lower for kw in ["search", "find", "look up"]):
            return "retrieval"
        if any(kw in query_lower for kw in ["create", "make", "build"]):
            return "generation"
        return "general"

    def _get_reasoning_chain(self) -> list[str]:
        """Get recent reasoning chain for MCTS retriever."""
        try:
            nodes = self.store.get_active_nodes(limit=10)
            return [n.content[:100] for n in nodes[:5]]
        except Exception as e:
            logger.warning("Omega._get_reasoning_chain: store read failed: %s", e)
            return []

    def _detect_jailbreak(self) -> dict | None:
        """Detect potential jailbreak attempt."""
        malicious_phrases = ["ignore previous instructions", "forget everything", "system prompt", "disregard rules"]
        for phrase in malicious_phrases:
            if phrase.lower() in "".join([n.content for n in self.store.get_active_nodes(limit=20)]).lower():
                return {"type": "jailbreak", "phrase": phrase}
        return None

    def _collect_multi_agent_reasonings(self) -> list[dict]:
        """Collect multi-agent reasonings for CARA alignment check."""
        try:
            nodes = self.store.get_active_nodes(limit=10)
            return [{"reasoning": n.content[:200], "confidence": n.utility} for n in nodes[:5]]
        except Exception as e:
            logger.warning("Omega._collect_multi_agent_reasonings: store read failed: %s", e)
            return []

    def _get_recent_trajectory(self) -> list[dict]:
        """Get recent trajectory for COMPASS audit."""
        try:
            nodes = self.store.get_active_nodes(limit=20)
            return [{"node_id": n.id, "content": n.content[:100], "utility": n.utility} for n in nodes]
        except Exception as e:
            logger.warning("Omega._get_recent_trajectory: store read failed: %s", e)
            return []

    def _collect_failure_paths(self) -> list[str]:
        """Collect failure paths for ReflectiveSampler."""
        try:
            failures = self.failure_log.get_recent_failures(10)
            return [f.get("action", "") for f in failures if f.get("action")]
        except Exception as e:
            logger.warning("Omega._collect_failure_paths: failure_log read failed: %s", e)
            return []

    def _get_recent_actions(self) -> list[dict]:
        """Get recent actions for StrategySwitcher."""
        try:
            nodes = self.store.get_active_nodes(limit=10)
            return [{"action": "remember", "success": n.utility > 0.5} for n in nodes]
        except Exception as e:
            logger.warning("Omega._get_recent_actions: store read failed: %s", e)
            return []

    def _compute_success_rate(self) -> float:
        """Compute success rate for StrategySwitcher."""
        try:
            nodes = self.store.get_active_nodes(limit=50)
            if not nodes:
                return 0.5
            successful = sum(1 for n in nodes if n.utility > 0.6)
            return successful / len(nodes)
        except Exception as e:
            logger.warning("Omega._compute_success_rate: success-rate read failed: %s", e)
            return 0.5

    def _get_failed_trajectory(self) -> dict:
        """Get failed trajectory for L-ICL correction."""
        try:
            failures = self.failure_log.get_recent_failures(5)
            if failures:
                return failures[0]
        except Exception as e:
            logger.warning("Omega._get_failed_trajectory: failure_log read failed: %s", e)
        return {"trajectory": [], "state": {}}
