# Prometheus Nexus 架构优化循环报告

> 自动优化循环: 发掘改进方案 → 执行改进 → push。共 39 轮, 全部已 push 到 origin/master。
> 原则(用户硬约束): **调度集中是上帝, 不可肢解**; 只外置器官/装配/决策, 不拆调度逻辑。
> 用户授权高风险项(按收益降序): 主循环护栏 → 遥测 HTTP 暴露 → **真拆 life.py 装配层**(九步) → **架构缺陷修复 #1-#3**。
> 所有改动零破坏既有行为, 由新增测试护栏保证。

## 一、累计成果(39 轮)

| # | 优化域 | 关键证据 |
|---|--------|----------|
| 1 | P1 机制声明式接入地基 | BaseMechanism 接入点 + wiring 收集器(9测试) |
| 2 | 死代码接活 + 延迟导入 + store首测 | CARA/CAMP 经 wiring 复活; import 子模块不再拉 uvicorn(19) |
| 3 | P0 存储批量写 | **实测 13.9x**(N=200, 逐条38.8ms→批量2.8ms) |
| 4 | evolution/CNS/Cortex 单测 | 21测试 |
| 5 | P2 机制级遥测地基 | 自动计时 + 收集器 + prometheus 格式 |
| 6 | P2 遥测接 Omega | `mechanism_telemetry()` 暴露 |
| 7 | harness 三模块单测 | active_compressor/tool_tax_gate/tiered_router(10) |
| 8 | 激进#1 外置 intent + Omega 护栏 | classify_intent/extract_tool_calls → intent.py(16+7) |
| 9 | 激进#2 外置信任标注 | annotate_trust → retrieval.py(5) |
| 10 | 激进#3 外置越狱检测 | detect_jailbreak → safety_utils.py(9) |
| 11 | 激进#4 外置5个节点统计 | store_stats.py(6) |
| 12 | 激进#5 外置2个失败日志 | failure_stats.py(4) |
| 13 | 激进#6 外置蒸馏奖励 | distill_bonus → distill.py(4) |
| 14 | 激进#7 外置账本逻辑 | is_duplicate_production/summarize_issues → ledger.py(6) |
| 15 | 架构优化总结报告 | docs/ARCH_OPTIMIZATION_REPORT.md |
| 16 | 主循环接遥测 | registry.invoke 自动计时(4) |
| 17 | P0 批量写接线 | Omega.seed_trusted_knowledge(3) |
| 18 | 激进#8 外置后见轨迹拼装 | build_hindsight_trajectory → hindsight.py(3) |
| 19 | 激进#9 外置日志→问题处理器 | IssueLogHandler/should_skip_issue → issue_handler.py(5) |
| 20 | 更新 19 轮成果报告 | docs/ARCH_OPTIMIZATION_REPORT.md |
| 21 | 遥测生产化出口 | Omega.diagnostics 合一诊断(3) |
| 22 | 主循环补单测起步 | remember 写入门护栏(3) |
| 23 | 更新报告至 22 轮 | docs/ARCH_OPTIMIZATION_REPORT.md |
| 24 | **高风险** 主循环 pipeline smoke 安全网 | learn/reflect/evolve/dream/maintain 全跑通(6) |
| 25 | **高风险** 遥测 Prometheus 导出 | `export_prometheus_metrics()`(3) |
| 26 | **高风险** 遥测 /metrics HTTP 端点 | `start_metrics_server()` 真实拉取(2) |
| 27 | **高风险** 真拆#1 装配层 | `_nexus_register_all` → omega/assembly.py |
| 28 | **高风险** 真拆#2 心跳线程 | `_heartbeat_loop` → omega/heartbeat.py |
| 29 | **高风险** 真拆#3 健康采集/聚合 | `_collect_component_health`+`_compute_health` → omega/health.py |
| 30 | **高风险** 真拆#4 监控统计 | `get_mechanism_consumption` → omega/monitor.py |
| 31 | **高风险** 真拆#5 语义健康 | `get_semantic_health` → omega/monitor.py |
| 32 | **高风险** 真拆#6 依赖深度 | `get_dependency_depth` → omega/monitor.py |
| 33 | **高风险** 真拆#7 成熟度评分 | `_compute_fitness` → omega/maturity.py(减~88行) |
| 34 | **高风险** 真拆#8 知识利用报告 | `knowledge_utilization_report` → omega/monitor.py |
| 35 | **高风险** 真拆#9 dopamine gate | `should_reject_dopamine` → omega/gates.py |

**累计**: 39 commit, **190 个新增测试全过**(快速集 ~3min), 远端同步。

## 二、从 life.py 外置的器官(保留上帝调度权)

调度逻辑(remember/recall/learn/reflect/evolve/dream/maintain 流程)**一行没改**。
仅把硬编码在函数体内的**纯函数/独立类器官**抽到 `mechanisms/` 模块, life.py 改委托壳:

| 模块 | 外置内容 | 原 life.py |
|------|----------|-----------|
| `intent.py` | `classify_intent`, `extract_tool_calls` | `_classify_intent`, `_extract_tool_calls` |
| `retrieval.py` | `annotate_trust` | `_recall_with_trust`(信任标注段) |
| `safety_utils.py` | `detect_jailbreak` | `_detect_jailbreak` |
| `store_stats.py` | 5 个节点统计 | `_get_reasoning_chain` 等 |
| `failure_stats.py` | `collect_failure_paths`, `get_failed_trajectory` | `_collect_failure_paths`, `_get_failed_trajectory` |
| `distill.py` | `distill_bonus` | `_distill_bonus` |
| `ledger.py` | `is_duplicate_production`, `summarize_issues` | `record_production`去重段, `_get_issues` |
| `hindsight.py` | `build_hindsight_trajectory` | `_mine_hindsight`(轨迹拼装段) |
| `issue_handler.py` | `IssueLogHandler`, `should_skip_issue` | `_attach_issue_handler` |

**共 13 个器官外置**(mechanisms/)。价值: 每个独立可单测; 主文件净减约 200 行。

### 2.1 真拆 life.py 装配层(omega/ 包, 用户授权高风险项)

调度逻辑(remember/recall/learn/reflect/evolve/dream/maintain/branch_*/record_*)**一行没拆**——
这些是直接调各子系统(被装配进 Omega 的属性)的"上帝编排", 拆了就丢了统一调度点。
仅把**与调度解耦的装配/统计/决策**抽到 `omega/` 包, life.py 改委托壳:

| 模块 | 外置内容 | 原 life.py | life.py 减行 |
|------|----------|-----------|-------------|
| `omega/assembly.py` | `register_all_mechanisms` | `_nexus_register_all`(机制注册+Nexus代理) | ~98 |
| `omega/heartbeat.py` | `run_heartbeat` | `_heartbeat_loop`(daemon线程) | ~28 |
| `omega/health.py` | `collect_component_health`, `compute_health` | `_collect_component_health`, `_compute_health` | ~55 |
| `omega/monitor.py` | `get_mechanism_consumption`, `get_semantic_health`, `get_dependency_depth`, `knowledge_utilization_report` | 对应4方法 | ~120 |
| `omega/maturity.py` | `compute_fitness` | `_compute_fitness`(10维度评分) | ~88 |
| `omega/gates.py` | `should_reject_dopamine` | remember 的 dopamine gate 决策 | ~11 |

**omega/ 包共 9 步真拆**, life.py 累计减约 **400+ 行**。所有外置均为委托壳,
行为逐行不变, 每步有委托一致性 + 结构验收测试。注入/写入副作用(rollback/failure_log)
仍留 life.py(上帝职责), omega/gates.py 只回答"是否拒绝"。

## 三、P0 存储批量写: 13.9x 的真实边界(诚实声明)

`create_nodes_batch` 在**纯 store 层**实测 N=200: 逐条 38.8ms → 批量 2.8ms = **13.9x**。
但**在 `remember` 在线路径不适用**(循环#15 已声明): remember 是 11 道安全门 +
每节点独立 wal 事务的重管道, 批量写只优化 store 锁+事务, 主瓶颈是安全门+事务,
强行批量会破坏单节点原子性与门失败隔离(安全退化)。

**接线落点(循环#17)**: `Omega.seed_trusted_knowledge(contents)` ——
仅限**可信离线种子**(本地语料/已审核文档), 跳过在线安全门, 直接走
`create_nodes_batch`(一次锁/事务)。在线路径仍必须经 remember 过门。
测试验证: 批量种子已 FTS 正确写入(`store.search` 可检索), 耗时显著低于逐条 remember。

## 四、机制级遥测(已闭环并接入主循环)

- 能力(循环#5-6): `BaseMechanism._metrics` + `wiring.run_phase` 自动计时/记错;
  `collect_registry_metrics(registry)` 聚合 + `export_prometheus_format` 导出;
  `Omega.mechanism_telemetry()` 暴露
- 接入(循环#16): `MechanismRegistry.invoke()` 是所有机制统一入口(硬编码调度也走它),
  改造为自动 `record_latency/record_error` → 主循环经 invoke 调度的机制**真实累积指标**
- 你叫 Prometheus 却长期无运行时机制指标的问题已解决(数据随管道推进自动产生, 待生产拉取)

## 五、剩余风险与下一步建议

**未外置的 life.py 方法**(上帝调度核心, 用户硬约束不可拆):
- `remember`/`recall` 主路径(统一写入/检索编排)
- `learn`/`reflect`/`evolve`/`dream`/`maintain` 流程(不可肢解)
- `branch_*`/`record_production`/`record_issue`(状态变更属上帝职责)

**高风险项已按收益降序全部做完**:
1. ✅ 主循环 pipeline smoke 安全网(#24)
2. ✅ 遥测 Prometheus 导出(#25)+ /metrics HTTP 端点(#26)
3. ✅ 真拆 life.py 装配层九步(#27-35, omega/ 7 模块)
4. ✅ dopamine gate 决策外置(#35)

**仍待人工评估(超出"外置装配"域, 需拆 God class 本身, 风险陡增)**:
- `life.py` 拆为多 mixin/文件(需重新设计导入拓扑, 当前委托壳模式已达安全边界)
- `get_pipeline_health` 外置(archive 文件路径依赖 `__file__`, 需先统一 paths 模块)

## 五之二、架构缺陷修复(#1-#3, 用户授权执行)

评审发现的真问题(非洁癖), 按 ROI 降序低风险修复, 每步测试守护:

| # | 缺陷 | 修复 | 验证 |
|---|------|------|------|
| 1 | `status().mechanisms=127` 硬编码魔法数, 与注释"236 机制"矛盾 | 新增 `_mechanism_count()` 读 Nexus 真相源(`get_monitor_snapshot()['mechanisms']`), 降级链 nexus>registry>0 | test_status_mechanism_count(3) + 更新 test_status_consistency |
| 2 | `status()` 每次调用全量重算(`_collect_component_health` 遍历所有组件 + `_compute_health` 查 store), /metrics 每 15s 拉取成瓶颈 | 加 5s TTL 缓存(uptime 实时刷新, 其余缓存; 懒初始化不碰 `__init__`) | test_status_ttl_cache(3) |
| 3 | `recall`(融合检索)与 `store.search`(原始 FTS) 语义割裂, seed 直写节点隐式不被 recall 返回 | recall docstring 文档化契约 + 新增 `search_raw()` 统一原始检索入口 + 契约测试 | test_recall_search_contract(3) |

> ⚠️ #3 过程中抓到真回归: patch 误删 `recall` 内 `start=time.time()`, 致 recall 抛 NameError(生产静默崩溃), 已加回并被测试捕获。这正是"每步全量测试"的价值。
>
> #3 的"统一"采用**文档化契约 + 提供显式入口**而非强行让 recall/store 一致 —— 因 recall 融合语义是设计核心, 强行统一会破坏信任/分支过滤。消除隐性坑, 不动行为。

## 六、自主循环机制

- cron 任务 `loop-optimize-nexus`(`44dd4e5fcbb9`, 每 30min, no_agent 脚本模式)
- 脚本 `~/.hermes/scripts/loop_optimize.py`: 自检 src/tests 改动 → 跑 187 快速测试基线(venv python 优先绕开 uv 联网) → 侦测下一可外置目标 → 报告状态
- 无消息时保活(监控基线、报告进度); 用户唤醒会话时立即续跑把侦测目标亲手做完

---

*生成于自动优化循环第 39 轮。所有 commit 已 push 至 origin/master。自动化安全域(外置纯函数/装配/决策)已清空, 后续仅剩需人工评估的 God class 重构。*
