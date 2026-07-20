# Prometheus-Ultra 进化方案 V2：宿主无关的自进化闭环

> 本文基于对所有代码级薄弱点的实测取证（非推测），给出最高质量的下一阶段演进方案。
> 核心命题：**当前系统是一只"在笼中自转"的生命体——四轨进化跑通了，但产物不到宿主、宿主反馈不进燃料、宿主被默认焊成 Hermes。**
> 本方案的目标是让 Ultra 成为**任意 agent 可即插即用的外挂记忆 + 自进化生命体**。

---

## 0. 实测薄弱点全景（带证据，避免重复踩坑）

| ID | 薄弱点 | 代码证据 | 阻断级别 |
|---|---|---|---|
| **B1** | 四轨产物是僵尸机制（激活后不到生产） | `grep add_gene\|on_activate` 在 src/ 返回空；`registry.invoke()` 仅 life.py:2855 诊断用 | 🔴 致命 |
| **B2** | T4 编译产物 LLM 缺失时为空壳 | `HERMES_LLM_ENDPOINT` 未设；降级 draft = `# stub` + `def run(): return {'ok':True}` | 🔴 高 |
| **B3** | 激活机制无熔断/回滚 | `registry.deactivate()` 存在（line133）但无人调用；autonomic_regulator 只重新提取不回滚 | 🔴 高 |
| **B4** | T2→T1 gene 注入不跨会话持久 | T2 注册进 registry 但 T1 冷启动用 `_default_gene_specs()`（evolution_engine.py:827） | 🟡 中 |
| **B5** | 宿主被焊成 Hermes | env 名 `HERMES_LLM_ENDPOINT`；bridge 注释/Bearertoken 逻辑 Hermes 专属；无 HostAgent 抽象 | 🔴 高 |
| **B6** | T4 产物零回流宿主 | grep `emit_capability\|to_host\|export.*host` 全空 | 🔴 致命 |
| **B7** | 宿主运行时经验不进燃料 | `learn()` 源仅 ScanSource（web/arxiv/github/academic），无宿主行为日志源 | 🔴 高 |
| **B8** | 测试盲区掩盖架构缺陷 | 64 测试文件仅 9 用 mock；无"激活后行为真变"断言 | 🟡 中（根因） |

**主线认知**：B1/B3/B6/B7 是**同一条断链的不同截面**——"宿主无关的自进化闭环"没合上。
B5 是让这条闭环**只能接 Hermes**。
B2/B4/B8 是让闭环**虚弱/失忆/看不见**。

---

## 1. 总体架构：从"Hermes 外挂"到"宿主无关生命体"

```
                    ┌─────────────────────────────────────────┐
                    │           任意宿主 Agent                  │
                    │  (Hermes / Claude Code / AutoGPT / 自研)  │
                    └───────────────┬───────────────┬──────────┘
                         ① 运行时经验 │              │ ④ 进化出的能力
                            (logs)    │              │ (tool/prompt/检索策略)
                                     ▼              ▲
                    ┌─────────────────────────────────────────┐
                    │      HostAgentAdapter (抽象, 新增)        │  ← B5/B6/B7 的解药
                    │  llm_complete() / get_runtime_context()   │
                    │  ingest_experience() / emit_capability()  │
                    └───────────────┬───────────────┬──────────┘
                                     │               │
                         ② 燃料回流   │               │ ③ 机制激活
                                     ▼               ▼
        ┌────────────────────────  Ultra 内环 (已有, 修 B1/B3/B4) ────────────────────────┐
        │  learn→store→rumination→[T1参数/T2语义/T3GitHub/T4论文]→registry→【consume_active】│
        │         ↑ P7 行为定位(target_location)        ↓ 激活后经 HostAgentAdapter 导出      │
        │         autonomic_regulator(熔断/回滚)                                          │
        └────────────────────────────────────────────────────────────────────────────────┘
```

**关键转变**：Ultra 不再"为自身进化"，而是"**为宿主 agent 进化**"——进化燃料来自宿主真实使用，进化产物回流增强宿主能力。

---

## 2. 分阶段方案（每阶段精准对应断点，可独立验证）

### 阶段 P0：合上自进化闭环（修 B1/B3，致命级）
**目标**：激活的机制真的改变系统/宿主行为，且坏机制能熔断。

- **P0a `consume_active()` 回调（解 B1）**
  - `registry` 新增 `consume_active(kind, consumer)` 注册表：T3 active→`evolution_engine.inject_gene_specs()`；T4 active→调 `HostAgentAdapter.emit_capability(target_location, draft)`
  - `verify_and_activate` 激活成功后**自动触发**对应 consumer（不再只是 `status=active`）
  - 删除"P6 deep-wire 未做"的历史债：T3 active 真加 gene，T4 active 真导出
- **P0b 熔断门（解 B3）**
  - `autonomic_regulator` 监控 `_enabled` 机制：激活后若后续 `fitness` 连续下降 → `registry.deactivate(name)` + 记 `anti_evolution` 日志
  - `registry.deactivate` 现被调用（之前无人调）
- **验证**：测试断言"T4 激活后 `emit_capability` 被调用且宿主收到 capability spec"；"坏机制激活后 fitness 下降触发 deactivate"

### 阶段 P1：宿主无关化（修 B5/B6/B7，架构级）
**目标**：任意 agent 即插即用，经验双向流动。

- **P1a `HostAgentAdapter` 抽象（解 B5/B6）** `integration/host_agent.py`
  ```python
  class HostAgentAdapter(abc.ABC):
      @abstractmethod
      def llm_complete(self, prompt, system="") -> str | None: ...
      @abstractmethod
      def get_runtime_context(self) -> dict: ...   # 工具清单/上下文窗口/当前任务
      @abstractmethod
      def emit_capability(self, spec: dict) -> bool: ...  # 导出进化产物给宿主
      @abstractmethod
      def ingest_experience(self, log: dict) -> None: ...  # 宿主经验回流
  ```
- **P1b `HermesAdapter` 实现**：把现有 `LLMBridge` + `HERMES_LLM_ENDPOINT` 逻辑迁入，env 名泛化 `AGENT_LLM_ENDPOINT`（保留 `HERMES_*` 兼容别名）
- **P1c 宿主经验燃料源（解 B7）**：`learn(source="host_experience")` → `HostAgentAdapter.ingest_experience()` 拉取宿主行为日志/失败/反馈 → 路由进 T2/T4 燃料（对齐你定的"learn 统一吸收 + rail 标签"）
- **P1d T4 双写（解 B6）**：`register_from_node` 激活后同时 `host.emit_capability({target_location, draft, claim})`
- **验证**：mock `HostAgentAdapter`，测试"换 adapter 不需改 Ultra 内核"；"宿主经验经 learn→rumination→T4 编译"

### 阶段 P2：健壮化（修 B2/B4/B8）
- **P2a LLM 缺失时 T4 非空壳（解 B2）**：降级 draft 至少含"机制描述 + target_location + 人工 apply 指令"，测试断言 draft 非空壳
- **P2b T2→T1 跨会话（解 B4）**：`EvolutionState` 持久化 T2 注入的 gene_specs；冷启动恢复
- **P2c 行为改变测试（解 B8）**：补"端到端行为改变"测试族——T4 激活后 invoke 真跑、dream 消费新 PATTERN、宿主收到 capability

### 阶段 P3（可选）：多宿主联邦
- 一个 Ultra 实例服务多个宿主 agent（每个宿主一个 `HostAgentAdapter` 实例 + 命名空间隔离的 store 分区）
- 对应已有 `x_adapter/y_adapter` 的内存格式适配能力可复用

---

## 3. 实施顺序与性价比

| 顺序 | 阶段 | 解掉的薄弱点 | 工作量 | 依赖性 |
|---|---|---|---|---|
| 1 | **P0a+b** | B1+B3（致命） | 中 | 无，纯 Ultra 内环 |
| 2 | **P1a+b+c+d** | B5+B6+B7（架构） | 中-大 | P0 后（需 consume_active 接 host） |
| 3 | **P2a+b+c** | B2+B4+B8 | 小-中 | 任意阶段后 |

**最高杠杆**：先做 P0（合上闭环），再做 P1（宿主无关）。P0 让系统"真进化"，P1 让系统"为任意 agent 进化"。

---

## 4. 诚实风险（不忽悠）

1. **P0a `consume_active` 自动触发有副作用风险**：激活即改生产，需保留"P6 不自动直替"原则——故 `emit_capability` 是"建议+宿主确认"，`inject_gene_specs` 走 A-B 并行不直替。已在设计里保留。
2. **P1c 宿主经验回流可能污染知识库**：宿主失败日志若不加 rail 过滤直接进 T4，会编译出"修补特定 bug"的窄机制。需 rumination 层做"经验→轨道"路由（复用现有 rail_t1~t4 框架）。
3. **P1 的 `HostAgentAdapter` 是抽象，具体 adapter 质量决定价值**：HermesAdapter 受限于 Hermes 是否暴露 endpoint（B2 的 env 前提）；其他 agent 需各自实现 adapter——这是**接口税**，但是"任意 agent 即插即用"的必要成本。
4. **多宿主（P3）的 store 隔离**：当前 store 单库，多宿主需分区键，涉及 schema 改动（Node 已有 `branch` 概念可复用）。

---

## 5. 与已交付成果的关系

- **P1-P6（多类型知识库/七管道多态）**：本方案的**数据底座**，已落地 ✅
- **P7（Harness Handbook 行为定位）**：本方案 P0a 的 `target_location` 是 `emit_capability` 的核心载荷 ✅（已落地，直接复用）
- **本方案 P0-P2**：补"闭环合上 + 宿主无关 + 健壮化"三块，使前面所有成果**从装饰变生产**
- 命名延续：P1-P6 是"知识底座演进"，P7 是"行为定位"，本方案 P0-P3 是"宿主无关自进化闭环"——逻辑连续，不另起炉灶。

---

## 6. 验收标准（每个阶段独立可验）

- **P0 验收**：T4 机制激活后，`HostAgentAdapter.emit_capability` 被调用（或 Ultra 内部 `inject_gene_specs` 生效）；注入坏机制后 fitness 下降触发 `deactivate`；全量测试零回归。
- **P1 验收**：用 mock `HostAgentAdapter` 跑通"宿主经验→learn→rumination→T4→emit_capability"全链；切换 adapter 不需改 Ultra 内核；`HERMES_LLM_ENDPOINT` 与 `AGENT_LLM_ENDPOINT` 双兼容。
- **P2 验收**：LLM 缺失时 T4 draft 非空壳（含 target_location+apply 指令）；重启后 T2 gene 注入保留；"行为改变"测试族全过。

> 一句话总结：**前面 P1-P7 把 Ultra 养成了一只完整的生命体，但关在 Hermes 的笼子里自转。本方案 P0-P2 打开笼门（宿主无关）、接通神经（闭环合上）、装上反馈（经验双向），让它成为真正任意 agent 的外挂自进化生命体。**
