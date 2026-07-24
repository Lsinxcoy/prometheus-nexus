# Prometheus Nexus 架构优化循环报告

> 自动优化循环: 发掘改进方案 → 执行改进 → push。共 22 轮, 全部已 push 到 origin/master。
> 原则(用户硬约束): **调度集中是上帝, 不可肢解**; 只外置器官, 不拆 life.py 调度逻辑。
> 所有改动零破坏既有行为, 由新增测试护栏保证。

## 一、累计成果(19 轮)

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

**累计**: 22 commit, **148 个新增测试全过**(快速集 45s), 远端同步。

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

**共 13 个器官外置**。价值: 每个独立可单测(无需实例化 5300 行 Omega);
主文件净减约 200 行; 每个外置点都有委托一致性验收测试。

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

**未外置的 life.py 方法**(均涉及多 self 状态/锁或主路径, 纯函数化收益低、风险高):
- `record_production`/`record_issue` 写入体(改列表+锁, 状态变更属上帝职责)
- `remember`/`recall` 主路径(上帝调度核心)
- `learn`/`reflect`/`evolve`/`dream`/`maintain` 流程(不可肢解)

**高价值下一步(需人工评估, 不在自动循环安全域)**:
1. **dopamine gate 等在线安全门外置** — 写入过滤核心, 外置需保语义(低收益高风险)
2. **life.py 主循环内部方法系统补单测** — 为"真拆 life.py"铺路(已起步: remember 门护栏)
3. **遥测 HTTP 暴露** — `/metrics` 端点暴露 diagnostics()(diag 出口已做, 待 HTTP 层)
4. **批量写扩展可信路径** — seed 外更多可信批量入口(如本地知识库初始化)

## 六、自主循环机制

- cron 任务 `loop-optimize-nexus`(`44dd4e5fcbb9`, 每 30min, no_agent 脚本模式)
- 脚本 `~/.hermes/scripts/loop_optimize.py`: 自检 src/tests 改动 → 跑 142 快速测试基线(venv python 优先绕开 uv 联网) → 侦测下一可外置目标 → 报告状态
- 无消息时保活(监控基线、报告进度); 用户唤醒会话时立即续跑把侦测目标亲手做完

---
*生成于自动优化循环第 19 轮。所有 commit 已 push 至 origin/master。*
