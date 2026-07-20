# Ultra 系统开发路径图（基于 git 时间线重建）

> 数据来源：旧仓库 `E:\Prometheus-Ultra` git 历史（2026-07-09 → 07-19，98 提交）
> + 当前仓库 `E:\Prometheus-Ultra-MultiTypeKB` git 历史（2026-07-18 → 07-19，94 提交）
> 不依赖会话记忆或文档摘要，全部为 git 硬证据 + 代码事实。

## 代码事实（实测）
- Python 文件：260 个 / 类定义：605 个 / 机制相关函数：70 个 / schema 常量：165 个
- 论文/来源引用（arxiv/doi/et al 等）：174 处 → 印证"引用论文超 100"
- 机制不集中在 `mechanism_registry`（仅 7 条探索/产物），而是散落在 B3-B10 论文模块、七管道、四轨进化、安全层（17）、记忆层（14）

## 开发阶段（git 时间线）

| 阶段 | 日期 | 核心工作 | 关键提交 |
|---|---|---|---|
| **B 系列机制实现** | 07-09~07-12 | 批量实现论文机制 STUB→MATCH：B3(B3-2 MCTS检索/B3-4时序权重/冲突检测)、B4(SleepGate/ExternalNotebook/FSFM)、B5(COMPASS/LOCA/CARA/MAC-Bench合规)、B6(HiMAC/G-STEP/L-ICL/TieredRouter/ReflectiveSampler)、B7/B8/B9/B10(多agent/FATE失败轨迹/Signals三方) | `feat(papers): B3~B10` 共 18 提交 |
| **PARTIAL→MATCH 深化** | 07-10~07-12 | 把 docstring 标 PARTIAL/STUB 的模块真实实现：LOCA/CAMP/DIG/KnowledgeCuration、memory_depth(STUB→MATCH, EVAF 惊喜-效价门控)、HeLa-Mem 扩散激活、paper citation 修正 | `fix: upgrade 8 PARTIAL` `fix: STUB→MATCH` |
| **S 系列系统加固** | 07-11~07-12 | S1 语义渗透(set_pipe_result 接入 7 管道)、S2 计数器写入、S5/S6 已知缺陷修复、arxiv HTTPS、移除配额限制、MonitoredDAG 兼容 | `S1~S6` 修复 |
| **P0-P2 集成** | 07-12~07-15 | 36 个独立模块集成进 life.py 主管道、反刍引擎(知识反刍+分布式同步)、OpenOPC 机制借鉴、全系统 E2E 验证 | `feat: integrate 36 isolated modules` |
| **P1-P6 演进版** | 07-16 | 四轨进化 + 多类型知识库 + 七管道多态感知（当前架构定型）、反刍重设计为 learn 温故知新环节、全量 E2E 1708 passed | `feat: 四轨进化+多类型知识库+七管道` |
| **分叉 + 监控强化** | 07-18~07-19 | 从旧仓库 clean 分叉为 MultiTypeKB；A-F 机制级监控(静默/孤岛/调用链/Tier1-3)、Owner-Harm 持久化、Phase G 全维度提分、看门狗 | 当前仓库 94 提交 |
| **薄弱点 50 循环** | 07-19（已停） | cron 每 30min 一轮，cycle 41-46，修静默 except/类型边界/持久化断点/并发锁 | `loop-41`~`loop-46` |

## 每日提交量（旧仓库）
```
07-09: 18   07-10: 10   07-11: 5    07-12: 5    07-13: 1
07-15: 2    07-16: 5    07-17: 2    07-19: 2
```

## B 系列批次与对应论文机制
- **B3**：MCTS 推理感知检索、时序权重、primacy bias、冲突检测
- **B4**：SleepGate(睡眠门)、ExternalNotebook(外部笔记本)、FSFM(安全/自适应)
- **B5**：COMPASS、LOCA、CARA、MAC-Bench 合规评分、干预控制、finetune 审计
- **B6**：HiMAC、G-STEP、L-ICL、TieredRouter、ReflectiveSampler
- **B7**：多 agent 文件系统
- **B8**：FATE 失败轨迹
- **B9/B10**：Signals 三方、剩余机制

---

## A 项验证结果：B 系列机制真实实现状态（代码事实，2026-07-19）

### 验证方法（两层，非 docstring 自称）
1. **定义层**：读 b*_remaining.py / safety/*.py 聚合文件核心方法，确认有真实算法骨架
2. **接入层**：grep `self.<mech>.<method>(` 在 life.py 主流程的调用次数

### 文件组织真相（修正"虚假繁荣"误判）
B 系列机制**不是独立文件**（compass.py/cara.py 等搜不到），而是**聚合进 `b7_remaining.py`(805行/5类)、`b8_remaining.py`(797行/11类)、`b9_remaining.py`(767行/6类)、`learning/b10_remaining.py`(644行/6类)、`safety/*.py`**。
**B10 已带入当前分支**（路径在 `learning/` 非 `evolution/`，此前误报 MISSING 已修正）：`SubtleMemoryBenchmark` 已接入 life.py:1969 真调用；其余 5 类(TokenArenaAdapter/RevisionDiscipline/KnowledgeToSkillPipeline/TraceUtility 等)为定义但零调用的实验机制。
`harness/himac_planner.py` 在当前分支确实存在(HiMACPlanner 已接入主流程，见接入层表)，此前 MISSING 误报亦修正。

### 接入层验证（life.py 主流程真实调用）
| 机制类 | 方法调用次数 | 状态 |
|---|---|---|
| sleep_gate | 2 | ✅ 真跑 |
| reflective_sampler | 2 | ✅ 真跑 |
| intervention_controller (COMPASS真身) | 1 | ✅ 真跑 |
| tiered_router | 1 | ✅ 真跑 |
| mcts_retriever (B3) | 1 | ✅ 真跑 |
| external_notebook (B4) | 1 | ✅ 真跑 |
| knowledge_curation | 1 | ✅ 真跑 |
| persona_manager | 1 | ✅ 真跑 |
| signal_triage (B8) | 1 | ✅ 真跑 |
| esteer (B8) | 1 | ✅ 真跑 |
| himac_planner (B6) | 1 | ✅ 真跑 |
| localized_icl (B6/L-ICL) | 1 | ✅ 真跑 |
| fate (B8 FATE) | 1 | ✅ 真跑 |
| **local_causal_explainer (LOCA)** | **0** | ⚠️ 死代码（实例化不调用） |
| **reasoning_alignment (CARA)** | **0** | ⚠️ 死代码（实例化不调用） |
| **camp_assembly (CAMP)** | **0** | ⚠️ 死代码（实例化不调用） |

### 真实结论（诚实）
1. **B 系列机制不是"虚假繁荣"**：13/16 个核心类在 life.py 主流程有真实 `.method()` 调用，是 MATCH 级真实现+真接入。
2. **3 个真死代码**：local_causal_explainer(LOCA)、reasoning_alignment(CARA)、camp_assembly(CAMP) —— 实例化但零方法调用，是 A 项查出的真实短板（之前评分/监控都没发现）。
3. **B10 批次缺失**：当前仓库无 b10_remaining.py，分叉时该批次论文机制（Signals 三方等）未迁入。
4. **机制真实总量**：605 类 / 260 文件 / 174 处论文引用；被主流程调用的核心机制约 50+（含七管道+四轨+安全层17+记忆层14），与"引用论文超100的大成版"一致。
5. **之前"机制消费率0%/装饰性架构"的判断错误**：根因是 `get_mechanism_consumption` 只盯 registry(7条)，漏掉这 50+ 真接入机制。

### 待修复（A 项产出）
- [ ] 3 个死代码机制：要么接入主流程（LOCA/CARA/CAMP 真调用），要么从实例化列表移除（避免虚假计数）
- [ ] B10 批次缺失：确认是设计性移除还是分叉遗漏，补回或显式标注

---
*本文件由 git 硬证据 + 接入层代码验证重建，替代基于记忆/摘要/单注册表的不可靠判断。*
