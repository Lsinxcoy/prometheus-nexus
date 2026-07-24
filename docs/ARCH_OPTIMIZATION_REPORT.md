# Prometheus Nexus 架构优化循环报告

> 自动优化循环: 发掘改进方案 → 执行改进 → push。共 14 轮, 全部已 push 到 origin/master。
> 原则(用户硬约束): **调度集中是上帝, 不可肢解**; 只外置器官, 不拆 life.py 调度逻辑。
> 所有改动零破坏既有行为, 由新增测试护栏保证。

## 一、累计成果

| # | commit | 优化域 | 关键证据 |
|---|--------|--------|----------|
| 1 | `c3af909` | P1 机制声明式接入地基 | BaseMechanism 接入点 + wiring 收集器(9测试) |
| 2 | `3601151` | 死代码接活 + 延迟导入 + store首测 | CARA/CAMP 经 wiring 复活; import 子模块不再拉 uvicorn(19) |
| 3 | `4614bfb` | P0 存储批量写 | **实测 13.9x**(N=200, 逐条38.8ms→批量2.8ms) |
| 4 | `ebc4061` | evolution/CNS/Cortex 单测 | 21测试 |
| 5 | `f9625a0` | P2 机制级遥测地基 | 自动计时 + 收集器 + prometheus 格式 |
| 6 | `ef9064c` | P2 遥测接 Omega | `mechanism_telemetry()` 暴露 |
| 7 | `a305c91` | harness 三模块单测 | active_compressor/tool_tax_gate/tiered_router(10) |
| 8 | `1fd1f0c` | 激进#1 外置 intent + Omega 护栏 | classify_intent/extract_tool_calls → intent.py(16+7) |
| 9 | `9b1304d` | 激进#2 外置信任标注 | annotate_trust → retrieval.py(5) |
| 10 | `d2d765c` | 激进#3 外置越狱检测 | detect_jailbreak → safety_utils.py(9) |
| 11 | `617e046` | 激进#4 外置5个节点统计 | store_stats.py(6) |
| 12 | `45d50ea` | 激进#5 外置2个失败日志 | failure_stats.py(4) |
| 13 | `575fc24` | 激进#6 外置蒸馏奖励 | distill_bonus → distill.py(4) |
| 14 | `966e2f2` | 激进#7 外置账本逻辑 | is_duplicate_production/summarize_issues → ledger.py(6) |

**累计**: 14 commit, **133 个新增测试全过**, 远端同步。

## 二、从 life.py 外置的器官(保留上帝调度权)

调度逻辑(remember/recall/learn/reflect/evolve/dream/maintain 流程)**一行没改**。
仅把硬编码在函数体内的**纯函数子器官**抽到 `mechanisms/` 独立模块, life.py 改委托壳:

| 模块 | 外置函数 | 原 life.py 方法 |
|------|----------|------------------|
| `intent.py` | `classify_intent`, `extract_tool_calls` | `_classify_intent`, `_extract_tool_calls` |
| `retrieval.py` | `annotate_trust` | `_recall_with_trust`(信任标注段) |
| `safety_utils.py` | `detect_jailbreak` | `_detect_jailbreak` |
| `store_stats.py` | `collect_reasoning_chain` 等 5 个 | `_get_reasoning_chain` 等 5 个 |
| `failure_stats.py` | `collect_failure_paths`, `get_failed_trajectory` | `_collect_failure_paths`, `_get_failed_trajectory` |
| `distill.py` | `distill_bonus` | `_distill_bonus` |
| `ledger.py` | `is_duplicate_production`, `summarize_issues` | `record_production`去重段, `_get_issues` |

价值:
- 每个器官现在**独立可单测**(无需实例化 5333 行 Omega)
- 算法逻辑与上帝解耦, 后续可由 wiring 声明式收集
- 主文件从 5333 行净减约 120 行, 且每个外置点都有委托一致性验收测试

## 三、P0 存储批量写: 13.9x 的真实边界(诚实声明)

`create_nodes_batch` 在**纯 store 层**实测 N=200: 逐条 38.8ms → 批量 2.8ms = **13.9x**。
但**在主循环 `remember` 路径不适用**:

`remember` 是重管道 —— 11 道安全门(input_guardrail → five_gate_chain → oep →
memory_write_guard → forbidden_pattern → trigger_detector → dopamine → five_gates →
constitution → instincts → rubric → veracity), 每节点**独立过门 + 独立 wal 事务**。
批量写只优化 store 锁+事务, 但主循环瓶颈是**安全门 + 每节点事务**, 不是 store 锁。
强行批量会破坏"单节点原子性 + 门失败隔离"(安全退化)。

**结论**: 13.9x 是真实但局部的收益(适合离线批量导入/外部知识灌库),
不应套进 `remember` 在线路径。这是实验数据推翻"无证据倍数声明"的典型案例。

## 四、机制级遥测(已闭环)

- `BaseMechanism._metrics` + `wiring.run_phase` 自动计时/记错
- `collect_registry_metrics(registry)` 聚合 + `export_prometheus_format` 导出 Prometheus text
- `Omega.mechanism_telemetry()` 暴露 → 宿主/监控可周期拉取或 `/metrics` 暴露
- 你叫 Prometheus 却长期无运行时机制指标的问题已解决(能力就位, 待生产接入)

## 五、剩余风险与下一步建议

**未外置的 life.py 方法**(均涉及多 self 状态/锁, 纯函数化收益低、风险高, 按低风险原则不强行外置):
- `_mine_hindsight` / `_attach_issue_handler`(依赖 event_bus/hindsight_miner/record_issue)
- `record_production`/`record_issue` 写入体(改列表+锁, 状态变更属上帝职责)

**高价值下一步(需人工评估, 不在自动循环安全域)**:
1. **store 批量写接线到离线导入路径**(非 remember 在线路径) — 让 13.9x 在知识灌库生效
2. **dopamine gate 决策外置** — `remember` 的门是写入过滤核心, 外置需保持门语义
3. **life.py 主循环接入遥测** — 在 learn/evolve 后调 `mechanism_telemetry()` 周期导出
4. **更激进: 真拆 life.py** — 需先把主循环内部方法也补单测护栏(目前仅有本地管道 smoke)

## 六、自主循环机制

- cron 任务 `loop-optimize-nexus`(`44dd4e5fcbb9`, 每 30min, no_agent 脚本模式)
- 脚本 `~/.hermes/scripts/loop_optimize.py`: 自检 git 干净度 + 跑全量测试基线(venv python 优先绕开 uv 联网) + 侦测下一个可外置目标
- 无消息时保活(监控基线、报告进度); 用户唤醒会话时立即续跑把侦测目标亲手做完

---
*生成于自动优化循环第 14 轮。所有 commit 已 push 至 origin/master。*
