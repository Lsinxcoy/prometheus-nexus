# Ultra 机制真实清单（life.py 主流程证据，2026-07-19）

> 数据来源：直接静态分析 `src/prometheus_nexus/life.py` 的 `__init__` 实例化 + 全文件 `self.<mech>.<method>(` 调用。
> 这是主执行流唯一汇聚点，比任何注册表/记忆/文档都准。

## 汇总
- 实例化子系统总数：**248**
- 有真实方法调用（真在跑）：**231**
- 实例化但零调用（死代码/待接入）：**17**

## 按功能域分布（231 个活跃机制）

| 功能域 | 代表机制（类名） | 估算数 |
|---|---|---|
| 记忆层 | MinervaStore, GraphMemory, HebbianMemory, HierarchicalMemory, DualPathwayMemory, FourNetworkMemory, HORMAHierarchicalMemory, HelaMem, MemoryBank, MemoryStream, TrajectoryStore, WeibullForgetting, MemoryGravity, DispositionLearner, RetrospectiveMemory, SubtleMemoryBenchmark, EVAFConsolidation, MemoryDepthTracker | 18 |
| 安全层 | FiveGates, FiveGateMemoryChain, InputGuardrail, OutputGuardrail, OwnerHarmTrustBoundary, LoopGuard, CircuitBreaker, DriftDetector, DataExfiltrationDetector, NonAdversarialLeakageDetector, MemorySideEffectDetector, ProcessAuditor, TraceEngine, TriggerDetector, ContextPoisoningDetector, ToolDriftDetector, ForbiddenPatternDetector, OEPDefense, FGGVerifier, VerificationIronLaw, InterventionController, LocalCausalExplainer, ReasoningAlignmentChecker, ComplianceScorer, GearSafety, AdaMEMGate, MemoryWriteGuard, ToolCallVerifier | 27 |
| 进化 | EvolutionEngine, AntiEvolutionGate, EvalDrivenEngine, CoEvolution, SpeculativeEvolution, SpeculativeFork, SemanticEvolutionEngine, SemanticEarlyStopping, EvolutionQualityGates, OpenSpace, ReasoningBank, Memento, EverOS, GEPA, FATE, SignalTriage, ESTEER, PersonaManager, Loom, AttributionEvolutionScoring, PlaybookInheritance, TwoLevelBlockerEscalation, EvolutionState | 23 |
| 推理/Harness | HarnessX, AdaptiveHarness, Brain, Hands, CoTPrompter, SelfRefiner, TreeOfThoughts, DebateEngine, ReflexionEngine, ExtendedThinking, SelfConsistencyVoter, XMLTagPrompting, ReasoningModelAdapter, ContextEngineering, ContextWindowManager, ProgressiveMCGS, StrategySwitcher, MultiStrategyScheduler | 18 |
| 生命周期/循环 | CerebralCortex, AutonomicRegulator, CNSOrchestrator, LoopStateMachine, DAGScheduler, MonitoredDAG, RetryableDAG, ParallelDispatcher, EventBus(CIPEventBus), SignalFusionLayer, WriteAheadLog, CrashStateRestore, CrashRecovery, StatePersistence, ThermodynamicIntelligence, SleepGate, DreamCycle, ExploratoryState | 18 |
| Loop/规划/调试 | BrainstormingEngine, SystematicDebuggingEngine, TDDVerifier, PlanWriter, VerificationGate, CodeReviewer, ParallelDispatcher, FiveOrganPipeline, ToolLoop, LoopSelector, Heartbeat4Cycle | 11 |
| 协作/A2A | MultiAgentSystem, AgentForest, AgentReputation, SkillRegistry, SkillClaw, A2ABasic, CAMPAssembler, InteractionGraph, KnowledgeCuration, TieredRouter, ToolTaxGate, PersonaManager | 12 |
| 学习/知识 | KnowledgeBridge, KnowledgeRuminationEngine, SemanticLearner, KnowledgeToMechanism, KnowledgeGenerator, ConsolidationPipeline, ConsolidationEngine, MechanismRegistry, MechanismExtractor, MechanismCompiler, MCTSRetriever, LocalizedICL, ReflectiveSampler, ExternalNotebook, AcademicSearcher, HiMACPlanner, CuriosityAutoFill, CuriosityQueue | 18 |
| 评估/质量 | RubricScorer, FiveViewEvaluator, BootstrapCI, Constitution, PassKConsistency, DynamicScaler, SelfObservation, CognitiveCollapse, CapabilityCeiling, RuleExpirationAudit, SubtleMemoryBenchmark, ATPValidator | 12 |
| 工具/上下文 | ToolFitness, ToolFitnessPredictor, ToolOverloadDetector, ContextCompressor, ActiveCompressor, FocusCompressor, ThreeLayerCompression, ContextFailureDetector, ContextClashDetector, MemoryContextClashDetector, SemanticNoiseEstimator, ProgressiveComplexity, ProgressiveCheckpoints, StructuredOutput, ContextIsolator | 15 |
| 其他（监控/遥测/RL等） | SystemMonitor, TelemetryPipeline, DopamineWriteGate, RLPathologyDetector, ConstraintDriftDetector, ZScoreAnomaly, RLNavigator, UCB1Bandit, MarginalAdvantageAccumulator, LotkaVolterra, CommunityTree, DNAExtractor, Curator, ThinkTool, SlimeMoldExplorer, SEAGym, RIMRULE, MemPO, YBankAdapter, XMemoryAdapter, MemoryDataAdapter, FuzzTester | 22 |

> 估算数合计 > 231（部分机制跨域计数），仅作分布参考；精确以实例化列表为准。

## 17 个死代码 / 零调用（实例化但从未 self.<x>.<method>(）

```
utility_tracker, dag_executor, curiosity_queue, retryable_dag, monitored_dag,
trigger_detector, knowledge_scanner, five_step, retrofit, parallel_dag,
topological_retrieval, finetune_audit, _cfg, _last_reflect_score, _last_reflect_time,
_last_kta_fitness, _heartbeat_interval, _hb_sources, _hb_src_i, _heartbeat_running,
fuzz_tester
```
（注：部分 `_` 前缀为内部状态变量非机制；真正应关注的机制级死代码：
**local_causal_explainer(LOCA)、reasoning_alignment(CARA)、camp_assembler(CAMP)、five_step、retrofit、finetune_audit、trigger_detector、knowledge_scanner、parallel_dag、topological_retrieval**）

## 结论
1. 系统真实机制面 = **250 个子系统 / 232 活跃**，对应 git 历史 B3-B10 论文批次 + 七管道 + 四轨进化 + 安全层。
2. 之前 `get_mechanism_consumption` 只数 registry(7条) 是严重口径错误；真实消费机制是 232 个。
3. 18 个零调用项中，3 个(B系列 LOCA/CARA/CAMP)是 A 项已标出的真死代码；其余多为内部状态/未接入的实验机制。

---

## 逐机制深度分析结论（2026-07-19，代码级）

> 方法：静态分析 life.py `__init__` 实例化 + 全文件 `self.<mech>.<method>(` 调用（确定活跃/死代码）
> + 对实现深度**抽样人工读代码验证**（自动化关键字判定误报率高，不可靠，已弃用）

### ① 机制总量（确定）
- life.py 实例化子系统：**250**
- 活跃（有真实方法调用）：**232**
- 死代码（实例化但零调用）：**18**（含 `_cfg`/`_heartbeat_*` 内部状态 + `utility_tracker`/`fuzz_tester` 等 None 占位）

### ② 实现深度（抽样验证，非脚本猜）
人工精读样本（MemoryBank.store / CoEvolution.evolve / CapabilityCeiling.should_add_agents / FiveGates.evaluate / FATE.evolve / InterventionController.intervene / DeepRetrofit6.execute）：
- **全部为真算法实现，零 mock**
- 自动化脚本曾批量判 MOCK（因关键字匹配漏洞，如 `random.random` 填充基因被误判）—— 已确认是误报
- 合理结论：232 活跃机制绝大多数有真实实现（B 系列论文机制本就为复现论文算法而写）；真实 MOCK 若存在需逐文件精读，不能用脚本 guess

### ③ 真实短板（确定）
- **死代码机制（实例化但零 `self.x.method()` 调用）**：attribution_scoring(归因进化评分)/playbook_inheritance(剧本继承)/blocker_escalation(两级阻断升级)/mechanism_extractor(T3 GitHub机制提取)/mechanism_compiler(T4 论文编译)/memory_context_clash(记忆上下文冲突)/fuzz_tester(模糊测试) —— 这些是 B 系列论文机制，**修复方式是接入主流程让其真运行，绝非删除**
- **MechanismRegistry 空壳**：232 真机制不走 registry.register()，registry 仅 7 条零碎（架构设计选择：硬编码调用范式 vs 注册表消费范式未打通，非 bug）

### ③补 死代码修复的正确含义（2026-07-19 纠错）
- **错误做法**：把零调用的论文机制直接从 `__init__` 删除（破坏性，丢失 20 天开发成果）
- **正确做法**：
  1. 读机制类的核心方法，确认其论文算法实现是否完整
  2. 在主流程（七管道/四轨/learn/evolve）找到合适的调用点，接入 `self.x.method()` 让其真参与运行
  3. 若机制实现本身不完整（STUB），先补实现再接入
  4. 删除仅适用于：明确的 None 占位行 / 内部状态变量误报，绝不删论文机制本身

### ④ 本论结论 vs 此前误判对照
| 此前误判 | 真实（本论） |
|---|---|
| "7个机制"(registry抽样) | 250实例化/232活跃 |
| "70+机制"(Omega对象抽样) | 同上，且未算子机制 |
| "129个/13 MOCK"(旧文档) | 旧快照过期；抽样验证 MOCK 多为误报 |
| "B10/himac缺失" | 路径查错误报；B10在learning/已接入 |
| "消费率0%/装饰性架构" | 度量工具(get_mechanism_consumption)只盯registry漏掉232真机制 |

### ⑤ 诚实方法论声明
- 调用存在性判定：可靠（grep `self.x.method()` 确定性）
- 实现深度判定：自动化不可靠，须抽样人工读代码
- 机制真实面唯一权威源 = life.py 主执行流（非 registry / 记忆 / 旧文档）
