# Agent × Ultra 一体化接入指南 (V3)

> 设计目的: Agent+Ultra 是一套整体, 同样实现进化。但 Agent 源码永不被 Ultra 被动修改(安全边界)。

## 核心架构

```
Agent (任意LLM)  ──UltraClient SDK──>  Ultra (独立进程 :9200)
   │                                      │
   ├─ LLM配置注入 (AGENT_LLM_*) ─────────>│ T3/T4 复用 Agent LLM 编译机制 [G2]
   ├─ report_experience ─────────────────>│ 经验回灌 → Ultra 进化燃料
   └─ apply_capability <──────────────────│ emit_capability (建议+确认, 不改Agent源码)

Ultra 自身进化不依赖 Agent: evolve/ruminate/T1-T4 全在 Omega 内部自驱。
```

## 安全边界(硬保障)

1. Ultra **永不改 Agent 源码** — emit 只产"建议"(spec), Agent `apply_capability` 自决。
2. Agent LLM key [REDACTED] 仅内存(env注入), 不写 Ultra 的 store/node。
3. 多 Agent 隔离 — 每个 Agent 独立 `host_id`, 经验/机制按 host_id 分区(V2.1 C5)。
4. Ultra 崩溃不影响 Agent — 所有调用超时降级(NullHost 语义)。

## 快速接入

```python
from prometheus_nexus.client import UltraClient, LLMConfig

# 1. Agent 把自己的 LLM 配置注入(让 T3/T4 复用)
llm = LLMConfig.from_env()  # 读 AGENT_LLM_ENDPOINT / AGENT_LLM_API_KEY

# 2. 启动 Ultra 进程(独立运行, 注入 LLM 配置)
#    AGENT_LLM_ENDPOINT=... AGENT_LLM_API_KEY=... python -m prometheus_nexus.services.api_server

# 3. Agent 接入
ultra = UltraClient(base_url="http://localhost:9200", host_id="my_agent", llm_config=llm)

# 4. 超级记忆强化
ultra.remember("用户偏好 X")
hits = ultra.recall("X 相关")            # 8路由+future-aware+时间邻域融合

# 5. 驱动 Ultra 进化
ultra.evolve("从经验学习")               # 返回 chain_trace(链完整性)
ultra.ruminate()

# 6. 调用所有机制
ultra.compile_mechanism(arxiv_id="2505.18605")  # T4, 复用 Agent LLM
ultra.extract_mechanism(source="github", query="rate limiter")

# 7. 双向闭环
ultra.report_experience([{"type": "feedback", "content": "...", "utility": 0.8}])
# Ultra 进化后 emit → Agent 轮询 inbox → ultra.apply_capability(name)
```

## 接入层四缺口修复(V3)

| 缺口 | 修复 | 文件 |
|---|---|---|
| G2 T3/T4 复用 Agent LLM | `LLMConfig.from_env()` + Omega 优先注入 | `integration/llm_config.py`, `life.py` |
| G3 任意 Agent 接入 | `GenericAgentAdapter`(host_id 自报) | `integration/host_agent.py` |
| G1 全机制端点 | `/mechanisms`,`/t3/extract`,`/t4/compile`,`/ruminate`,`/evolve/chain`,`/utility/report` | `services/api_server.py` |
| G4 官方 SDK | `UltraClient` | `client.py` |

## 验证

- `tests/test_v3_agent_integration.py`: G2/G3/G1/G4 全覆盖
- 全量 E2E: 1738+ passed
