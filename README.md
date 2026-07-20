# Prometheus Ultra — MultiTypeKB

> 外挂记忆 / 自进化生命体的大脑（Nexus 神经系统统一中枢架构）

`Prometheus-Ultra` 是一套**自进化的知识生命体**：以多类型知识库（MultiTypeKB）为长期记忆，7 条认知管道（remember / recall / evolve / learn / reflect / dream / maintain）驱动持续进化，并通过 `Nexus` 神经中枢统一调度全部机制、共享记忆、执行优势强化路由与突触修剪。

---

## 1. 设计定位

```
Ultra = 外挂记忆 / 自进化生命体的大脑
Nexus = 这套神经系统的【统一神经中枢】
```

Nexus 统辖：

| 维度 | 内容 |
|---|---|
| 机制层 | 236 基本盘机制 + 动态层（T3/T4 编译产物） |
| 7 管道 | remember / recall / evolve / learn / reflect / dream_cycle / maintain |
| 两层记忆 | ① 知识记忆（MinervaStore，7 管道共享）；② 机制经验记忆（effect 账本，机制共享"什么有效/有害"） |
| 效果路由 | 动态机制实战更优则接管基本盘对应功能（fallback 永驻） |
| 突触修剪 | 效果账本负向机制自动 deactivate |

### Nexus 核心不变量（防回归）

- **Nexus 是仲裁者，不是执行者**。机制执行后端仍是 `life.py` 的实例（`self.x`）。`dispatch()` 查状态/效果/路由后转调 `self.x.method()`，**绝不双重执行**。
- **不吞并 MinervaStore / ModelRouter**（数据层 / 后端层，仅引用）。
- **236 基本盘机制全注册，零丢失**。
- **第二层统一调度**：全部 227 个非管道机制实例被 `NexusProxy` 透明包裹，任何 `self.x.method()` 调用透明过 Nexus（记账 + 效果路由），**零侵入 5000 行调用点**。

---

## 2. Nexus 四层架构（演化路线）

本仓库的 `feat/nexus-cns` 分支按四层渐进式构建了统一神经系统。**每一层都已通过严格测试 + 深度审计 + 9200 端口端到端验证**。

### Layer 1 — 神经中枢（统一注册 + 两层记忆 + 效果路由 + 突触修剪）
提交 `8bb3382`

- `Nexus.register_mechanism` / `register_pipeline` / `mount_dynamic`
- `dispatch()`：状态/效果/路由仲裁后转调执行后端
- `record_effect()`：机制经验记忆（effect 账本）
- `prune_harmful()`：突触修剪
- `get_consumption()`：机制消费真实统计（替代旧 `get_mechanism_consumption` 的 6 载体聚合漏算）

### Layer 2 — 统一调度（NexusProxy 透明代理）
提交 `32f496b`

- `NexusProxy` 包裹全部 227 个非管道机制实例
- 任何 `self.x.method()` 透明过 Nexus（记账 + 效果路由），**不改写 5000 行调用点**
- 代理设计：`__getattr__` 转发到真实实例，**不双重执行**（底层实例是唯一执行者）
- 代码级核查：全仓库无 `isinstance(self.x)` 检查，仅 `is not None`（代理透明满足）

### Layer 3 — T4 真实神经发生 + 监控统合
提交 `346db74`（部分）

- **T4 真实神经发生闭环**：修复 `_consume_t4` 中 `MechanismSandbox.load` → `compile_mechanism`（沙箱无 `load` 方法，原路径永远失败被静默吞掉）。修复后 `learn → extract → compile → nexus.mount_dynamic` 完整闭环打通。
- **监控统合真相源**：`Nexus.get_monitor_snapshot()` 统一监控视图（机制层 / 动态层 / 路由 / 修剪 / 静默机制）。`get_mechanism_consumption` 删除冗余的 6 载体聚合，改为委托 Nexus 真相源（保留静默机制诊断分类）。

### Layer 4 — 注册表统合进 Nexus 分类
提交 `346db74`（部分）

- `_nexus_register_all` 末尾同步 `SkillRegistry` / `InstinctsRegistry` 进 Nexus 分类视图
- Nexus 分类现含：`memory / lifecycle / evolution / safety / learning / general / harness / loop / execution / skill / monitor / pipeline / instinct / compiled`
- 原注册表保留不破坏

---

## 3. 机制数据流（真实路径）

```
learn(source, query)
  └─ mechanism_extractor.extract_from_node(node)        # T3: 提取候选基因
  └─ mechanism_compiler.compile_from_node(node)         # T4: 编译论文机制
       └─ _consume_t3({...})  → evolution_engine.inject_gene_specs(...)   # 注入进化引擎
       └─ _consume_t4({...})
            ├─ host.emit_capability(spec)                # 建议+宿主确认(对齐 P6 不自动直替)
            └─ MechanismSandbox().compile_mechanism(name, draft, base_mechanism)
                 └─ nexus.mount_dynamic(name, inst)      # 神经发生: 新机制长入动态层

运行时调用 self.x.method():
  └─ NexusProxy(self.x) 透明转发
       ├─ nexus.mark_invoked(name)                       # 记账
       ├─ route_override 检查 → 动态层接管则转动态实例    # 效果路由
       └─ getattr(real_instance, method)(...)            # 唯一执行
```

---

## 4. 统合映射（Nexus 是统一视图）

| 原分散系统 | 统合方式 |
|---|---|
| 236 机制实例（`self.x`） | Nexus 注册 + `NexusProxy` 包裹（统一调度） |
| 7 管道 | Nexus 注册（统一触发/协同/记忆读写） |
| MinervaStore（知识记忆） | Nexus 引用不替换（数据层） |
| effect 账本（经验记忆） | Nexus 内部（机制共享"有效/有害"） |
| SkillRegistry / InstinctsRegistry | Nexus 分类视图（启动同步） |
| SystemMonitor / Heartbeat（系统指标） | 正交保留（CPU/内存等），机制监控读 Nexus 真相源 |
| 9 调度器（heartbeat/loop 等） | 未统合（逻辑 delicate，回归风险高，按计划保留） |

---

## 5. API 服务（端口 9200）

启动：

```bash
cd /e/Prometheus-Ultra-MultiTypeKB
.venv/Scripts/python.exe -m prometheus_nexus.services.api_server --port 9200
```

| 端点 | 说明 |
|---|---|
| `GET /api/v1/health` | 健康检查 |
| `GET /api/v1/status` | 系统状态（含 Nexus 真实统计：机制数 / 管道 / 调用记账 / 消费率） |
| `GET /api/v1/nervous/cns` | Nexus 神经中枢详情 |
| `GET /api/v1/mechanisms` | 机制列表 |
| `POST /api/v1/remember` | 记忆管道 |
| `POST /api/v1/recall` | 回忆管道 |
| `POST /api/v1/evolve` | 进化管道 |
| `POST /api/v1/learn` | 学习管道（触发 T3/T4 神经发生） |
| `POST /api/v1/reflect` | 反思管道 |
| `POST /api/v1/dream` | 梦境管道 |
| `POST /api/v1/maintain` | 维护管道 |
| `GET /api/v1/dashboard` | 仪表盘 |
| `GET /api/v1/nodes` / `branch` / `owner` / `utility` / `ruminate` / `t` / `report_usage` | 其他查询端点 |

### status 端点返回的 Nexus 真实数据示例

```json
{
  "nexus": {
    "stats": { "mechanisms": 240, "pipelines": 7, "total_invocations": 1537 },
    "consumption": {
      "total": 240, "consumed": 206, "rate": 0.858,
      "by_category": { "safety": 40, "evolution": 34, "general": 38, ... }
    }
  }
}
```

> 消费率从旧架构的 **0%（6 载体漏算）** 提升到 **~0.86（Nexus 真实统计）** —— 这是"机制真被消费"而非"假绿"的关键证明。

---

## 6. 测试与深度审计

### 单元测试（`tests/test_nexus_cns.py`）

```bash
.venv/Scripts/python.exe -m pytest tests/test_nexus_cns.py -q
```

16 个严格测试覆盖：

| 测试 | 验证 |
|---|---|
| `test_zero_mechanism_loss` | Nexus 包含所有 life.py 机制（零丢失）+ 统合 skill/instinct |
| `test_seven_pipelines_registered` | 7 管道全注册 |
| `test_consumption_real_via_nexus` | 消费率读 Nexus 真实数据（非旧 0%） |
| `test_t4_dynamic_mount` | T4 沙箱编译 + 动态挂载 |
| `test_effect_routing_and_prune` | 效果路由 + 突触修剪闭环 |
| `test_e2e_seven_pipelines_run` | 实例化 → 跑 7 管道 → 机制真被调用（非假绿） |
| `test_layer2_unified_dispatch_proxy` | NexusProxy 包裹 + 透明记账 |
| `test_layer2_effect_routing_via_proxy` | 效果路由经代理生效 |
| `test_t4_real_neurogenesis_via_consume` | [Layer3] `_consume_t4` 真实神经发生 |
| `test_layer3_monitor_snapshot_source` | [Layer3] 监控统合真相源 |
| `test_layer4_skill_instinct_in_nexus` | [Layer4] 注册表统合分类 |

另含 `tests/test_deadcode_mechanisms_wired.py`（5 个测试，验证 6 个论文机制已接入主流程而非删除）。

### 深度审计（`scripts/audit_nexus_cns.py`）

```bash
.venv/Scripts/python.exe scripts/audit_nexus_cns.py
```

10 项全部通过（A–J）：

| 项 | 验证 |
|---|---|
| A zero_loss | life 机制数 == Nexus 机制数（零丢失） |
| B no_double_exec | 代理透明转发真实实例（不双重执行） |
| C base_persist | 基本盘永驻（动态层可修剪，基本盘不删） |
| D two_memory | 两层记忆（store 引用 + effect 账本） |
| E pipelines_run | 七管道真实运行（记账累加） |
| F t4_neurogenesis | T4 动态挂载 + dispatch |
| G layer2_unified_dispatch | 227/227 机制被代理包裹 + 透明 |
| H t4_real_neurogenesis | `_consume_t4` 真实沙箱编译 + 挂载 |
| I monitor_unified_source | 监控统合 Nexus 真相源 |
| J registry_unified | Skill/Instinct 进 Nexus 分类 |

---

## 7. 端到端验证（9200 真实服务）

```bash
# 启动
.venv/Scripts/python.exe -m prometheus_nexus.services.api_server --port 9200

# 七管道真实调用
for ep in remember recall evolve learn reflect dream maintain; do
  curl -s -o /dev/null -w "$ep:%{http_code}\n" -X POST http://localhost:9200/api/v1/$ep \
    -H "Content-Type: application/json" \
    -d '{"content":"e2e","query":"e2e","context":"e2e","source":"web","max_results":1,"limit":3,"confidence":0.5}'
done
# 全部返回 200

# 查 Nexus 真实统合状态
curl -s http://localhost:9200/api/v1/status | python -c "import sys,json; d=json.load(sys.stdin); print(d['nexus']['stats'])"
# {'mechanisms': 240, 'pipelines': 7, 'total_invocations': 1537, ...}
```

---

## 8. 运行环境

- Python 3.11（`.venv` 虚拟环境）
- 依赖：`MinervaStore`（知识记忆）、`wrapt`（未使用，已改为纯 Python 代理）、LLM 桥接（anthropic / volc-ark）
- 配置：`ZConfig`（database_path 等）
- 持久化：`archive/nexus.json`（Nexus 状态）、`archive/mechanisms.json`（旧注册表兼容）

### 快速启动 Omega（Python）

```python
from prometheus_nexus import Omega, ZConfig
omega = Omega(config=ZConfig(database_path="ultra.db"))
omega.learn(source="web", query="neural nexus", max_results=2)
omega.remember(content="x", utility=0.9, tags=["t"])
omega.recall("x")
omega.evolve(context="x", confidence=0.6)
omega.dream_cycle()
omega.maintain()
omega.reflect(context="x")
print(omega.nexus.get_monitor_snapshot())
```

---

## 9. 已知约束与未做项

| 项 | 状态 |
|---|---|
| cronjob 把 ultra 运行状态发飞书 | **未做**（独立任务） |
| 9 调度器（heartbeat/loop）退化成 Nexus 策略插件 | 未做（逻辑 delicate，保留） |
| 管道抽取（life.py 5000 行 → pipelines/ 包） | 用户确认**不做**（避免回归） |
| 动态机制经 learn 真实触发神经发生 | **已做**（Layer 3 修复 `_consume_t4`） |

### 设计哲学（用户要求）

- **统一调度中心降低维护成本**：Nexus 是仲裁者，机制执行后端仍在 life.py
- **不丢失任何一个机制**：基本盘永驻，动态层可修剪
- **透明代理零侵入**：不改写 5000 行调用点即可统合调度
- **真实数据非假绿**：消费率 / 调用记账来自 Nexus 真实统计，非聚合漏算

---

## 10. 提交历史（feat/nexus-cns）

```
346db74 feat(nexus): 第三/四层深化 — T4真实神经发生 + 监控统合 + 注册表统合
32f496b feat(nexus): 第二层统一调度 — NexusProxy 包裹全部机制, 调用透明过 Nexus
8bb3382 feat(nexus): 神经系统统一中枢 — 统合机制层+7管道+两层记忆+效果路由+突触修剪
43c7a0e feat: 全量接入6个论文机制到主流程(修复死代码, 非删除)
```

`main` 分支未改动。所有改动隔离在 `feat/nexus-cns`。
