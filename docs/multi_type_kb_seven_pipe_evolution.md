# Prometheus-Ultra 系统级演进方案：多类型知识库 × 四轨进化 × 七管道革新

> 本文档为系统演进的**最高层设计**，所有改动锚定真实代码接口（基于 2026-07-16 代码取证）。
> 核心命题：**从"均匀知识图 + 单一进化"演进为"多类型复杂知识库 + 四轨协同进化 + 七管道多态感知"**。

---

## 〇、关键事实更正（避免错误前提）

代码取证发现：**Ultra 的 schema 已经是 Ω 级多类型设计**——
- `foundation/schema.py` 已有 **44 个 NodeType**（FACT/CONCEPT/SKILL/PROCEDURE/PATTERN/HYPOTHESIS/BELIEF/TOOL/AGENT...）
- 已有 **40+ 个 EdgeType**（含 `PROVENANCE_DERIVED_FROM`、`EVOLUTION_SPECIATED`、`SKILL_DEPENDS_ON`、`BELIEF_SUPPORTS` 等）

**所以"知识库会变成多类型"不是未来的事——schema 已经支持。真正缺口是：**

1. **管道没用上类型**：`learn()` 写节点时 `self.remember(content=..., utility=..., tags=...)` **不传 NodeType**（life.py:2706），所有外部知识落默认类型（FACT），44 种枚举被浪费。
2. **T3/T4 产物在 store 外**：机制草案存 `MechanismRegistry`（独立 dict，`registry.py:self._mechanisms`），技能存 `skill_registry`——与 store 三分裂，违反"七管道共享记忆和知识积累"。
3. **dream 用独立 `_memories` list**（dream_cycle.py:44），不读 store 的多类型节点。
4. **recall/maintain/reflect 假设均匀节点**：113 处读节点无类型区分。

**结论：演进不是"扩展 schema"，而是"让管道真正使用已有 schema + 统一存储"。**

---

## 一、目标架构：统一多类型知识底座

```
┌─────────────────────────────────────────────────────────────┐
│             MinervaStore (统一多类型知识库)                    │
│  NodeType 已存在44种, 演进=按类型写入+消费:                    │
│   FACT(现有) | CONCEPT(语义) | PROCEDURE(参数) |              │
│   PROJECT(github) | PAPER(论文) | SKILL(技能) |              │
│   PATTERN(机制草案) | HYPOTHESIS(dream产出) | BELIEF(信念)    │
│  EdgeType 已存在40+, 演进=启用衍生边:                         │
│   PROVENANCE_DERIVED_FROM(论文→机制)                         │
│   SKILL_DEPENDS_ON / EVOLUTION_SPECIATED                     │
└───────────────────────────┬─────────────────────────────────┘
                            │ 七管道共享同一份多态积累
        ┌───────┬───────┬───────┬───────┬───────┬───────┬───────┐
       remember recall  learn   reflect evolve  dream  maintain
        (写多态)(按轨   (吸收+   (跨类型 (T1+T2+ (跨类型 (按类型
                 检索)   分类路由) 分析)  消费T3/T4)联想)  维持)
                            │
                    【反刍层: 温故知新 + 分类路由】
                    (重学沉睡节点 + 打 NodeType + 供给燃料)
                            │
        ┌──────────┬──────────┬──────────┬──────────┐
       T1参数     T2语义     T3提取     T4编译
       (读PROCEDURE)(读CONCEPT)(读PROJECT)(读PAPER)
```

**设计原则（用户确定）**：
- 专门管道做专门事：learn 统一吸收，七管道共享记忆，知识按多样性路由到四轨。
- 明确分工提高效率：源只拉一次（learn），下游消费不重拉。
- 反刍是"知识→轨道"的翻译层（温故知新）。

---

## 二、四轨进化：独立 vs 管道内（已查实）

| 轨 | 当前位置 | 归属 |
|---|---|---|
| T1 参数 | `evolve()` 内 (life.py:2357) | ✅ 管道内 |
| T2 语义 | `evolve()` 内 (life.py:2363) | ✅ 管道内 |
| T3 提取 | `autonomic_regulator` 触发 (autonomic_regulator.py:256) | ❌ 独立 |
| T4 编译 | `autonomic_regulator` 触发 (autonomic_regulator.py:267) | ❌ 独立 |

**当前设计合理**：T1/T2 每次 evolve 必跑（内部微调），T3/T4 按需触发（外部借力/超前探索，省成本）。
**缺口**：T3/T4 触发后只 `register` 进 registry，**激活执行路径未接**（半截闭环）。

---

## 三、七管道演进详细方案（每条锚定代码）

### 3.1 remember — 写多态节点
**现状**：`self.remember(content, utility, tags)` 不传 NodeType（life.py:2706）。
**演进**：
- `remember()` 增加 `node_type: NodeType = NodeType.FACT` 参数
- 外部知识写入时按类型路由：
  - 含参数值模式（`lr=0.01`）→ `NodeType.PROCEDURE`
  - 概念/定义型 → `NodeType.CONCEPT`
  - github 项目 → `NodeType.PROJECT` + 存 `url`
  - 论文 → `NodeType.PAPER` + 存 `url`（全文引用）
  - 技能 → `NodeType.SKILL`
- **锚点**：`life.py:2706` 的 `self.remember(...)` 加 `node_type=` + `url=`

### 3.2 recall — 按轨感知检索
**现状**：按 utility/相关性统一检索，无类型区分。
**演进**：
- 增加 `recall(node_type: NodeType | None = None)` 过滤
- T1 进化问参数知识 → `recall(node_type=PROCEDURE)`
- T4 编译问论文知识 → `recall(node_type=PAPER)`
- 实现：store 查询加 `type` 过滤（MinervaStore 已有 type 字段）

### 3.3 learn — 吸收 + 分类路由（核心枢纽）
**现状**：吸收一切→均匀 FACT 节点，丢 url。
**演进**（用户确定方案）：
- 写入时存 `url`（不丢源地址）
- 写入后按 source/content 打**轨道标签**（tags 或独立字段）：
  - `source=='github'` → `rail_t3`
  - `source in (arxiv, academic, report)` → `rail_t4`
  - 含参数值 → `rail_t1`
  - 概念型 → `rail_t2`
- 设 NodeType（见 3.1）
- **锚点**：`life.py:2706-2711` + 新增 `_classify_rail(node, source, content)`

### 3.4 reflect — 跨类型分析
**现状**：读最近节点做跨分析，假设均匀。
**演进**：
- 分析时区分节点类型：CONCEPT 冲突 ≠ PROCEDURE 冲突 ≠ PAPER 矛盾，处理策略不同
- 启用 `LOGICAL_CONTRADICTS` / `BELIEF_REFUTES` 等已有 EdgeType
- **锚点**：reflect 方法（life.py:2952）的节点遍历段

### 3.5 evolve — 多类型知识驱动
**现状**：T1+T2 管道内，T3/T4 独立候选。
**演进**：
- T1 读 `PROCEDURE` 节点派生基因维度（强化 P0-2）
- T2 读 `CONCEPT` 节点做语义进化（已做）
- T3/T4 激活路径接入：验证门通过后，`MECHANISM` 节点（PATTERN 型）经 `EVOLUTION_SPECIATED` 边连回系统
- **锚点**：evolve() 内 T2 段（life.py:2360-2370）+ autonomic 触发（autonomic_regulator.py:243）

### 3.6 dream — 跨类型联想
**现状**：用独立 `_memories` list（dream_cycle.py:44），不读 store 多类型。
**演进**：
- dream 读 store 多类型节点（而非独立 list）
- 跨界联想：CONCEPT × PAPER × PATTERN 组合 → 产出 HYPOTHESIS（新机制假设）
- 启用 `PROVENANCE_DERIVED_FROM` 边连接"论文→梦境假设"
- **锚点**：dream_cycle.py:44 `_memories` → 改读 store

### 3.7 maintain — 按类型差异化维持
**现状**：全局 utility 降权 + 清理，假设均匀。
**演进**：
- `PATTERN`/`PAPER`/`SKILL` 节点长留（高价值，不全忘）
- `FACT` 普通节点可清理
- `PROJECT` 节点定期刷新（github 项目可能更新）
- 启用 `MEMORY_CONSOLIDATED` / `MEMORY_FORGOTTEN` 边
- **锚点**：maintain 方法（life.py:3509 附近）的 decay 段

---

## 四、反刍机制角色（用户核心关切：温故知新）

**定位：知识分类路由器 + 轨道燃料库**（位于 learn 吸收之后、四轨消费之前）

三层职责：
1. **维持（已有）**：沉睡重学、utility 重评估、模式晋升 skill
2. **分类路由（新增核心）**：反刍重学每条节点时，基于 SemanticLearner+KTM 重学结果打 **NodeType + 轨标签**（rail_t1~t4），把"知识多样性"显式编码进 store
3. **燃料供给（新增）**：反刍盘点结果通知 autonomic_regulator——
   - 发现 `rail_t3` 节点堆积但未提取 → 优先触发 T3
   - 发现 `rail_t4` 论文但未编译 → 优先触发 T4

**闭环**：反刍（温故）→ 打标签路由 → 四轨消费（知新）→ 产出新机制/知识 → 反刍重学（再温故）。

**锚点**：`knowledge_rumination.py:101 ruminate()` + `life.py:2919` 调用点。

---

## 五、统一存储：消除三分裂

**现状**：store（知识）+ MechanismRegistry（机制草案）+ skill_registry（技能）三分裂。
**演进**：
- T3/T4 编译产物：写 `MECHANISM` 节点（NodeType=PATTERN）进 store + `PROVENANCE_DERIVED_FROM` 边连源论文/项目
- 技能：写 `SKILL` 节点进 store
- MechanismRegistry / skill_registry 保留为**元数据索引**（不重复存内容）
- **好处**：七管道共享同一份多类型积累（用户原则），dream/evolve/recall 能消费机制产物

**锚点**：`mechanism_compiler.py:10`（存 archive/compiled）→ 改为同时写 store 节点；`registry.py:self._mechanisms` 改为索引。

---

## 六、实施路线图（分阶段，每阶段可独立验证）

| 阶段 | 任务 | 锚点 | 风险 |
|---|---|---|---|
| **P1 地基** | learn 写节点存 url + 设 NodeType + 打 rail 标签 | life.py:2706 | 低（纯写入扩展） |
| **P2 反刍路由** | 反刍重学时打 NodeType + rail 标签 + 供给燃料 | knowledge_rumination.py:101 | 低 |
| **P3 消费对齐** | T3/T4 改为从 store 取 rail 节点（不重拉源） | mechanism_extractor.py:55 / compiler.py:58 | 中（需 store 查询） |
| **P4 统一存储** | T3/T4 产物写 MECHANISM/SKILL 节点进 store | compiler.py:10 / registry.py | 中 |
| **P5 管道多态** | recall 按类型 / maintain 按类型 / dream 读 store | 各管道方法 | 中 |
| **P6 闭环激活** | T3/T4 验证门通过后经边连回系统 | autonomic_regulator.py:243 | 高（需验证门） |

**推荐起步**：P1 → P2 → P3（打通"learn 吸收→反刍路由→四轨消费"闭环，消除源重复），再 P4/P5/P6。

---

## 七、质量保障（用户方法论）

1. **每条改动锚定真实接口**（NodeType 枚举已存在、store type 字段已存在、registry 已活）
2. **不破坏现有**：分阶段，每阶段跑四轨集成测试 + 核心 E2E（已 222 passed）
3. **消除冗余而非新增**：源只拉一次（learn），T3/T4 消费不重拉
4. **明确分工**：learn 吸收、反刍路由、四轨各做各事
5. **可验证**：每阶段有量化指标（节点类型分布、rail 标签命中率、机制激活成功率）

---

## 八、已落地 vs 待做

**已落地（本会话）**：
- ✅ 四轨框架（T1 持久化 / T2 语义 / T3 提取 / T4 编译）
- ✅ LLM 桥（HTTP 模式建桥 + 降级）
- ✅ 神经系统四轨调度（autonomic_regulator 触发 T3/T4）
- ✅ 四轨集成测试 5 passed + 核心 E2E 222 passed

**待做（本文档）**：
- ⬜ P1-P6 七管道多态演进
- ⬜ 反刍分类路由（层 2/3）
- ⬜ 统一存储（消除三分裂）
- ⬜ T3/T4 激活闭环（P6）

---

*文档生成于 2026-07-16，基于 Prometheus-Ultra 代码实查。所有锚点为真实行号，可直接定位实施。*
