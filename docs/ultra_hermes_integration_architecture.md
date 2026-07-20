# Prometheus Ultra ↔ Hermes Agent 整体接入方案

> 版本: 1.0 | 日期: 2026-07-04

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                    Hermes Agent                             │
│  ┌───────────────┐  ┌─────────────────┐  ┌───────────────┐  │
│  │ memory_provider│  │  agent/memory_  │  │ tools/        │  │
│  │  ABC (接口)     │  │  manager.py    │  │ memory_tool.py│  │
│  └───────┬───────┘  └────────┬────────┘  └───────┬───────┘  │
│          │                   │                     │          │
│          ▼                   ▼                     ▼          │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  plugins/memory/ultra/ (Hermes 插件)                │     │
│  │  ┌────────┐  ┌──────────┐  ┌───────┐  ┌─────────┐  │     │
│  │  │__init__│  │provider  │  │adapter│  │config   │  │     │
│  │  │.py     │  │.py       │  │.py    │  │.py      │  │     │
│  │  └────────┘  └────┬─────┘  └───┬───┘  └─────────┘  │     │
│  └────────────────────┼────────────┼────────────────────┘     │
│                       │            │                          │
└───────────────────────┼────────────┼──────────────────────────┘
                        │ HTTP      │
                        ▼            ▼
┌──────────────────────────────────────────────────────────────┐
│              Prometheus Ultra 服务 (端口 9200)              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  src/prometheus_nexus/                                │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌──────┐│  │
│  │  │life    │ │memory  │ │learning│ │services │ │organs││  │
│  │  │.py     │ │/       │ │/       │ │/api_    │ │/     ││  │
│  │  └───┬────┘ └───┬────┘ └───┬────┘ └───server │ └──────│  │
│  │      │           │          │         .py     │        │  │
│  │      ▼           ▼          ▼           │              │  │
│  │  7条管道: remember/recall/evolve/       │              │  │
│  │  learn/reflect/dream/maintain           │              │  │
│  │  + 127 机制 + ω 引擎                    │              │  │
│  └─────────────────────────────────────────┼──────────────┘  │
└────────────────────────────────────────────┼─────────────────┘
                                             │
┌────────────────────────────────────────────┼─────────────────┐
│           Feishu 飞书 (用户界面层)          │                 │
│  oc_32fe68a6179ed8a4339512c873ca835a       │                 │
│  ← 消息 ↔ 管道结果                          │                 │
└────────────────────────────────────────────┘                 │
                                                               │
┌────────────────────────────────────────────┐                 │
│  Cron 定时任务                             │                 │
│  • ultra-dream-reflect (每30min)           │                 │
│    → dream → reflect → maintain           │                 │
│  • prometheus-watchdog (每30min, 已暂停)    │                 │
│  • prometheus-full-monitor (每60min, 已暂停)│                 │
└────────────────────────────────────────────┘                 │
```

---

## 2. 组件分层详解

### 2.1 插件入口层 — `plugins/memory/ultra/__init__.py`

**文件**: `~/.hermes/hermes-agent/plugins/memory/ultra/__init__.py`

```python
def register(ctx):
    from plugins.memory.ultra.provider import UltraMemoryProvider
    ctx.register_memory_provider(UltraMemoryProvider())
```

Hermes 插件系统在启动时自动调用 `register(ctx)`，将 `UltraMemoryProvider` 注册为内存提供者。

**工作原理**: Hermes 扫描 `plugins/memory/ultra/` 目录，调用 `register()` 注入 provider 实例。提供者的生命周期与 Hermes 进程绑定。

### 2.2 提供者层 — `provider.py`

**文件**: `plugins/memory/ultra/provider.py` (449行)

`UltraMemoryProvider` 实现了 `MemoryProvider` abstract base class，是接入的核心。它做三件事：

| 职责 | 实现 | 说明 |
|------|------|------|
| **实现 MemoryProvider 接口** | `add()`, `scan()`, `replace()`, `remove()` | 将 Hermes 原生内存操作映射到 Ultra 管道 |
| **暴露 Hermes 工具** | `get_tool_schemas()` → 8 个 `ultra_*` 工具 | 模型直接调用 `ultra_remember/recall/evolve/learn/reflect/dream/maintain/status` |
| **控制会话生命周期** | `initialize()`, `shutdown()`, `sync_turn()`, `prefetch()` | 对话摘要自动保存 + 定期 dream 触发 |

**关键映射关系**:

```
Hermes MemoryProvider 接口     →    Ultra 管道
────────────────────────────────────────────────
add(content, utility, tags)    →    remember (POST /api/v1/remember)
scan(query, limit)             →    recall (POST /api/v1/recall)
replace(node_id, content)      →    evolve (POST /api/v1/evolve)
remove(node_id)                →    maintain (POST /api/v1/maintain)
sync_turn(user_msg, asst_msg)  →    remember (摘要保存) + 定期 dream()
prefetch(query)                →    recall (预取上下文)
```

**故障转移**: 当 Ultra 服务不可用时，自动回退到 `BuiltinFallback` (内置内存提供者)。

**系统提示注入**: `system_prompt_block()` 返回的提示告诉模型它拥有 Ultra 7 管道可用。

### 2.3 HTTP 适配器层 — `adapter.py`

**文件**: `plugins/memory/ultra/adapter.py` (209行)

`UltraAdapter` 是对 Ultra REST API 的同步 HTTP 客户端封装，使用 `httpx` 库。

| 方法 | API 端点 | 说明 |
|------|---------|------|
| `health_check()` | `GET /api/v1/health` | 心跳检测 |
| `status()` | `GET /api/v1/status` | 完整系统状态 |
| `remember()` | `POST /api/v1/remember` | 存储到记忆图 |
| `recall()` | `POST /api/v1/recall` | 多路由检索 |
| `evolve()` | `POST /api/v1/evolve` | 11 阶段进化 |
| `learn()` | `POST /api/v1/learn` | 外部知识获取 |
| `reflect()` | `POST /api/v1/reflect` | 5 视图自我评估 |
| `dream_cycle()` | `POST /api/v1/dream` | 记忆整合 |
| `maintain()` | `POST /api/v1/maintain` | 系统维护 |
| `branch_create/merge/list()` | `/api/v1/branch/*` | 分支管理 |

返回类型: `PipelineResponse` (dataclass) 和 `RecallResults` (dataclass)。

### 2.4 配置层 — `config.py`

**文件**: `plugins/memory/ultra/config.py` (48行)

`UltraConfig` 支持从 `config.yaml` 读取配置：

```yaml
memory:
  provider: ultra              # 激活 Ultra 提供者
  ultra:
    url: http://localhost:9200 # Ultra API 地址（默认）
    fallback: builtin          # 不可用时的回退策略
    auto_evolve: false         # 自动进化（默认关闭）
    dream_interval: 100        # 每 N 次对话轮触发一次 dream
```

### 2.5 回退层 — `fallback.py`

**文件**: `plugins/memory/ultra/fallback.py` (44行)

当 Ultra 服务不可及时发现时, `BuiltinFallback` 懒加载 Hermes 内置 `BuiltinMemoryProvider` 作为降级。

---

## 3. 数据流详解

### 3.1 写入流程 (ultra_remember)

```
用户/模型调用 ultra_remember("内容", utility=0.7)
    │
    ▼
provider.handle_tool_call("ultra_remember", args)
    │
    ▼
adapter.remember(content, utility, tags)
    │  POST /api/v1/remember
    ▼
Ultra Server (life.py::remember())
    │  1. 探索配额检查 can_explore()
    │  2. KnowledgeScanner 扫描 (超时重试)
    │  3. CuriosityQueue + UtilityTracker 更新
    │  4. 并行调度器处理
    │  5. GraphMemory 存储
    │  6. 返回 node_id
    ▼
返回 {"success": true, "node_id": "..."}
```

### 3.2 对话轮同步流程 (sync_turn)

```
每次用户/助手交互后自动触发
    │
    ▼
provider.sync_turn(user_msg, assistant_msg)
    │
    ├─ 1. 摘要用户-助手对话为 "U: ...\nA: ..."
    ├─ 2. adapter.remember(summary, utility=0.6, tags=["conversation"])
    ├─ 3. turn_counter++
    └─ 4. 如果 turn_counter >= dream_interval (100):
          └─ 后台线程 → adapter.dream_cycle()
```

### 3.3 定时任务流 (Cron)

系统有两个 Cron 任务持续运行：

#### ultra-dream-refresh (每30分钟, 已启用)

```
1. POST /api/v1/dream    → 记忆整合 (模式发现 + 信念合成)
2. POST /api/v1/reflect  → 自我反射 (5视图评估 + 热力学分析)
3. POST /api/v1/maintain  → 系统维护 (银行分层 + 自愈 + 诊断)
```

#### prometheus-full-monitor (每60分钟, 已暂停)
- 检查所有 57 组件状态
- 运行完整学习周期

#### prometheus-watchdog (每30分钟, 已暂停)
- no_agent=True (纯脚本模式, stdout 直接投递)

---

## 4. 模型端工具集 (Tool Schema)

`UltraMemoryProvider` 通过 `get_tool_schemas()` 向 Hermes 注册 8 个工具。模型在对话中可以直接调用它们：

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `ultra_remember` | 存储内容到记忆图 | content(str), utility(float, 默认0.7), tags(str[]) |
| `ultra_recall` | 多路由搜索记忆 | query(str), limit(int, 默认10) |
| `ultra_evolve` | 11阶段进化记忆 | context(str), branch(str, 默认main), confidence(float, 默认0.7) |
| `ultra_learn` | 外部知识获取 | source(str, 默认web), query(str), max_results(int, 默认5) |
| `ultra_reflect` | 自我评估 | context(str, 可选) |
| `ultra_dream` | 记忆整合 | branch(str, 默认main) |
| `ultra_maintain` | 系统维护 | 无参数 |
| `ultra_status` | 系统状态 | 无参数 |

---

## 5. 配置清单

### Hermes config.yaml 相关配置

```yaml
memory:
  memory_enabled: true          # 启用内存系统
  user_profile_enabled: true    # 启用用户画像
  write_approval: false         # 写入无需审批
  memory_char_limit: 2200       # 记忆字符限制
  user_char_limit: 1375         # 用户档案限制
  provider: ultra              # ← 关键: 使用 Ultra 提供者
  flush_min_turns: 6           # 最少对话轮数后刷新
  minerva_replacement: true    # Minerva 替代标志
  nudge_interval: 10           # 提示间隔
```

### 插件目录

```
%AppData%/Local/hermes/plugins/memory/ultra/
├── __init__.py         # 插件入口: register()
├── provider.py         # UltraMemoryProvider: 工具注册 + 管道映射
├── adapter.py          # UltraAdapter: HTTP 客户端
├── config.py           # UltraConfig: 配置读取
└── fallback.py         # BuiltinFallback: 故障转移
```

### Cron 任务文件

```
%AppData%/Local/hermes/cron/jobs.json
  ├── ultra-dream-refresh (每30分钟，已启用)
  ├── prometheus-full-monitor (每60分钟，已暂停)
  └── prometheus-watchdog (每30分钟，已暂停)
```

---

## 6. 故障排查指南

| 问题 | 可能原因 | 解决方法 |
|------|---------|---------|
| `ultra_*` 工具返回错误 "Ultra error" | Ultra 服务未运行 | 启动 `E:\\Prometheus\\Prometheus Ω` 服务 |
| 健康检查失败 | 端口配置错误 | 确认 `config.ultra.url` 或默认 `http://localhost:9200` |
| 写入回退到内置提供者 | Ultra 服务响应超时 | 检查 `timeout` 配置（默认30s），或检查服务负载 |
| 对话摘要未存储 | `sync_turn` 在 Ultra 不可用时跳过 | 检查 Ultra 可达性 |
| 定时任务未触发 | cron 调度器未运行 | `hermes gateway run` 启动 gateway |
| 记忆检索结果为空 | FTS5 或向量索引未构建 | 检查 Ultra 状态中 node_count |
| 插件未被加载 | 插件路径错误 | 插件必须位于 `%AppData%/Local/hermes/plugins/` 下 |

---

## 7. 架构特性总结

1. **七管道全覆盖**: remember/recall/evolve/learn/reflect/dream/maintain 全部通过 HTTP 暴露
2. **故障安全**: 内置提供者回退，服务恢复后自动启用
3. **自动记忆整合**: 每100轮对话触发 dream 后台线程
4. **工具即接口**: 8 个 `ultra_*` 工具让模型直接驱动 Ultra 能力
5. **定时维护**: Cron 任务每30分钟 dream→reflect→maintain
6. **配置驱动**: 所有参数通过 Hermes config.yaml 管控
7. **最小侵入**: 不修改 Hermes 核心，仅通过插件系统集成
