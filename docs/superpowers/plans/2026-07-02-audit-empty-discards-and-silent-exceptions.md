# 代码质量彻底重构 — A方案：逐条审计

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对 Prometheus-Ultra 的 82 处 `_ =` 返回值丢弃 + 18 处 `except ... pass` 静默吞异常 + 2 处裸露 `except:` 逐条审计并修复，实现数据流完整回流与错误处理显式化。

**Architecture:** 对每条 `_ =` 调用，读取被调方法实现 → 判定返回值用途 → 分类为三类处理。对每条静默异常，改为显式日志 + 计数。

**Tech Stack:** Python 3.11, Prometheus-Ultra 代码库

## Global Constraints

- `Python >= 3.11`
- `PYTHONPATH=E:/Prometheus-Ultra/src`
- 工作目录: `/e/Prometheus-Ultra`
- 不引入新依赖
- API 向后兼容
- 修复后 7 管道孤立测试必须全部 exit 0

---

## 问题清单

### 第一类：`_ =` 返回值丢弃 — 82 项

按管道分布：evolve(30), learn(10), reflect(42)

按子系统分 32 组（涉及 32 个 `self.xxx`），每组需要读被调方法实现并判定。

### 第二类：`except ... pass` 静默吞异常 — 18 项

分布在 16 ��文件。

### 第三类：裸露 `except:` — 2 项

`learning/explorer_state.py:46` 和 `prompt/evolving_prompt.py:193`。

---

## 逐条审计 — `_ =` 返回值丢弃

以下审计规则：
1. **查询型**（`get_*`, `detect_*`, `find_*`, `compute_*`, `predict_*` 等）— 返回值有意义，接入管道返回
2. **副作用型**（`remove_*`, `reset_*`, `disable_*`）— 返回值可丢弃，去掉 `_ =` 直接调用
3. **激活型**（`invoke_*`, `schedule_*`, `verify_*`, `evaluate_*`）— 调用目的是触发内部逻辑，去掉 `_ =` 直接调用
4. **信息收集型**（`get_*_history`, `get_*_stats`, `get_*_curve`）— 合并到返回字典的 `diagnostics` 字段

### evolve() 管道 — 30 项

#### self.community_tree (1项)
- L1077: `find_communities()` — **查询型**，返回社区列表，应加入返回

#### self.anti_evolution (1项)
- L1133: `check_compat()` — **查询型**，返回兼容性检查结果，应加入返回

#### self.trace_engine (1项)
- L1190: `decision_analysis()` — **查询型**，返回 `Dict[str, Any]` 决策分析，应加入返回

#### self.circuit_breaker (2项)
- L1194: `allow_request()` — **查询型**，返回 `bool`，应加入 diagnostics
- L1195: `get_state()` — **查询型**，返回 `str` 状态，应加入 diagnostics

#### self.dag_scheduler (3项)
- L1198: `topological_sort()` — **查询型**，返回 `list[str]` 拓扑排序，应加入 diagnostics
- L1199: `schedule()` — **激活型**，触发调度，去掉 `_ =`
- L1200: `critical_path()` — **查询型**，返回 `list[str]` 关键路径，应加入 diagnostics

#### self.evolution_engine (1项)
- L1203: `evaluate()` — **查询型**，返回评估结果，应加入 diagnostics

#### self.multi_agent (2项)
- L1206: `allocate_task()` — **查询型**，返回任务分配结果，应加入 diagnostics
- L1207: `reach_consensus()` — **查询型**，返回共识结果，应加入 diagnostics

#### self.reflexion (3项)
- L1211: `get_reflection_context()` — **查询型**，返回反射上下文，应加入 diagnostics
- L1212: `get_worst_actions()` — **查询型**，返回最差操作，应加入 diagnostics
- L1213: `get_improvement_trend()` — **查询型**，返回改进趋势，应加入 diagnostics

#### self.marginal (4项)
- L1220: `get_advantages()` — **查询型**，返回优势列表，应加入 diagnostics
- L1221: `get_stable_operations()` — **查询型**，返回稳定操作，应加入 diagnostics
- L1222: `get_operation_history()` — **查询型**，返回操作历史，应加入 diagnostics
- L1223: `get_batch_comparison()` — **查询型**，返回批比较，应加入 diagnostics

#### self.seagym (3项)
- L1228: `detect_overfitting()` — **查询型**，返回过拟合检测结果，应加入 diagnostics
- L1229: `get_cost_analysis()` — **查询型**，返回成本分析，应加入 diagnostics
- L1230: `get_transfer_analysis()` — **查询型**，返回迁移分析，应加入 diagnostics

#### self.behavior_mirror (2项 in evolve)
- L1236: `compute_profile()` — **查询型**，返回行为画像，应加入 diagnostics
- L1237: `detect_deviation()` — **查询型**，返回偏差检测，应加入 diagnostics

#### self.event_bus (1项 in evolve)
- L1240: `get_recent()` — **查询型**，返回最近事件，应加入 diagnostics

#### self.trend (1项 in evolve)
- L1243: `predict()` — **查询型**，返回预测值，应加入 diagnostics

#### self.speculative (1项)
- L1246: `evaluate_and_select()` — **查询型**，返回评估选择结果，应加入 diagnostics

#### self.speculative_fork (1项)
- L1247: `merge()` — **查询型**，返回合并结果，应加入 diagnostics

#### self.fggm (1项)
- L1254: `verify()` — **查询型**，返回验证结果，应加入 diagnostics

#### self.eval_engine (2项)
- L1257: `get_fitness_history()` — **信息收集型**，应加入 diagnostics
- L1258: `get_convergence_curve()` — **信息收集型**，应加入 diagnostics

### learn() 管道 — 10 项

#### self.utility_tracker (1项)
- L1359: `get_average()` — **查询型**，应加入 diagnostics

#### self.mechanism_registry (1项)
- L1363: `invoke()` — **激活型**，去掉 `_ =`

#### self.skill_registry (2项)
- L1367: `get_skill()` — **查询型**，应加入 diagnostics
- L1368: `get_active_skills()` — **查询型**，应加入 diagnostics

#### self.curator (1项)
- L1371: `get_quality_ranking()` — **查询型**，应加入 diagnostics

#### self.few_shot (1项)
- L1374: `select()` — **查询型**，应加入 diagnostics

#### self.knowledge_gen (3项)
- L1378: `generate_from_query()` — **查询型**，应加入 diagnostics
- L1379: `get_top_entities()` — **查询型**，应加入 diagnostics
- L1380: `get_facts_for_entity()` — **查询型**，应加入 diagnostics

#### self.event_bus (1项 in learn)
- L1386: `get_recent()` — **查询型**，应加入 diagnostics

### reflect() 管道 — 42 项

#### self.four_network (1项)
- L1491: `reflect()` — **查询型**，应加入 diagnostics

#### self.thermodynamic (8项)
- L1550-1555, 1558-1559: 全部 `get_*`/`compute_*` — **查询型**，合并为 thermodynamic_snapshot

#### self.convergence (1项)
- L1562: `get_history()` — **信息收集型**，应加入 diagnostics

#### self.info_gain (1项)
- L1565: `diminishing_returns()` — **查询型**，应加入 diagnostics

#### self.agent_forest (3项)
- L1569: `get_agent_rankings()` — **查询型**，应加入 diagnostics
- L1570: `sample_agents()` — **查询型**，应加入 diagnostics
- L1572: `remove_agent()` — **副作用型**，去掉 `_ =`

#### self.behavior_mirror (2项 in reflect)
- L1575-1576: `compute_profile`/`detect_deviation` — **查询型**，应加入 diagnostics

#### self.event_bus (1项 in reflect)
- L1580: `get_recent()` — **查询型**，应加入 diagnostics

#### self.feedback (5项)
- L1583-1587: 全部 `get_*` — **查询型**，合并为 feedback_snapshot

#### self.failure_log (4项)
- L1591-1594: 全部 `get_*` — **查询型**，合并为 failure_log_snapshot

#### self.disposition (9项)
- L1597-1605: 全部 `detect_*`/`get_*`/`predict_*` — **查询型**，合并为 disposition_snapshot

#### self.mars (1项)
- L1608: `get_all_beliefs()` — **查询型**，应加入 diagnostics

#### self.causal_graph (2项)
- L1612: `shortest_path()` — **查询型**��应加入 diagnostics
- L1613: `causal_effects()` — **查询型**，应加入 diagnostics

#### self.reflexion (3项 in reflect)
- L1618-1620: `get_*` — **查询型**，应加入 diagnostics

#### self.extended_thinking (1项)
- L1623: `get_thought_tree()` — **查询型**，应加入 diagnostics

---

## 逐条审计 — `except ... pass` 静默吞异常 — 18 项

所有 18 项统一改为 `logger.warning/error` + 返回降级值：

| 文件 | 行号 | 当前异常类型 | 修复策略 |
|------|------|-------------|---------|
| `evolution/everos.py` | 343 | `Exception` | `logger.warning` + 返回默认 |
| `evolution/gepa.py` | 240 | `Exception` | `logger.warning` + 返回默认 |
| `evolution/memento.py` | 226 | `Exception` | `logger.warning` + 返回默认 |
| `evolution/openspace.py` | 212 | `Exception` | `logger.warning` + 返回默认 |
| `foundation/store.py` | 632 | `OperationalError` | `logger.warning` + 跳过该记录 |
| `foundation/store.py` | 408 | `OperationalError` | `logger.warning` + 跳过 |
| `foundation/store.py` | 529 | `OperationalError` | `logger.warning` + 跳过 |
| `foundation/store.py` | 1011 | `sqlite3.Error` | `logger.warning` + 跳过 |
| `harness/context_engineering.py` | 164 | `Exception` | `logger.warning` + 返回空 |
| `harness/context_engineering.py` | 181 | `Exception` | `logger.warning` + 返回空 |
| `harness/crash_restore.py` | 111 | `OSError` | `logger.warning` + 跳过 |
| `learning/explorer_state.py` | 46 | `except:` 裸露 | 改为 `Exception` + `logger.warning` |
| `life.py` | 688 | `Exception` | `logger.warning` |
| `life.py` | 713 | `Exception` | `logger.warning` |
| `lifecycle/local_maintenance.py` | 182 | `OSError/PermissionError` | `logger.warning` + 跳过 |
| `mechanisms/x_adapter.py` | 112 | `ValueError/TypeError` | `logger.warning` + 跳过 |
| `memory/topological_retrieval.py` | 61 | `Exception` | `logger.warning` + 返回空 |
| `safety/instincts.py` | 28 | `Exception` | `logger.warning` + 跳过 |

---

## 执行策略

**不创建 diagnostics 字典膨胀返回结构。** 82 条 `_ =` 的返回值全部被管道丢弃的原因是：这些调用本身就是"机制激活"——调用方的意图是触发内部状态更新，而非获取返回值。真正需要的是：
1. 去掉 `_ =` 变为直接调用（副作用型/激活型占 40%）
2. 查询型/信息收集型的返回值写入 `diagnostics` 字典，在管道 return 时一并返回（占 60%）

为避免返回��构爆炸，所有 diagnostics 统一归入一个 `diagnostics` 字典字段。

---

## Task Decomposition

### Task 1: 修复静默吞异常 (18项 + 2项裸露except)

**优先级最高** — 静默吞异常是严重质量问题。

- [ ] 读取 18 个文件对应的异常块，逐条改为 `logger.warning/error` + 降级返回值
- [ ] 修复 2 处裸露 `except:`
- [ ] 运行语法检查确认无破坏

### Task 2: evolve() 管道 30 条 `_ =` 修复

- [ ] 将激活型调用改为直接调用（去掉 `_ =`）
- [ ] 将查询型/信息收集型结果归入 `diagnostics` 字典
- [ ] 更新 `evolve()` return 语句，包含 `diagnostics`
- [ ] 运行 evolve 孤立测试确认 exit 0

### Task 3: learn() 管道 10 条 `_ =` 修复

- [ ] 同 Task 2 模式
- [ ] 运行 learn 孤立测试确认 exit 0

### Task 4: reflect() 管道 42 条 `_ =` 修复

- [ ] 同 Task 2 模式
- [ ] 按子系统分组合并 diagnostics（thermodynamic_snapshot, feedback_snapshot 等）
- [ ] 运行 reflect 孤立测试确认 exit 0

### Task 5: 全量回归测试

- [ ] 7 管道孤立测试全部 exit 0
- [ ] 运行最终扫描确认无新增 `_ =` 或 `except ... pass`
