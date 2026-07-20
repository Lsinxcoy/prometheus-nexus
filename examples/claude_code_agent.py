"""Agent 接入示例: Claude Code.

展示 Claude Code(任意 LLM agent)如何作为 Ultra 的宿主, 经 UltraClient 接入:
- 注入自己的 LLM 配置(让 Ultra 的 T3/T4 复用)
- 用 Ultra 强化记忆(remember/recall)
- 驱动 Ultra 进化(evolve/ruminate)
- 消费 Ultra 产出的机制(apply_capability) — 不改 Claude Code 自身源码

运行: 设好 AGENT_LLM_ENDPOINT 后 `python examples/claude_code_agent.py`
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.client import UltraClient, LLMConfig


def run_claude_code_agent():
    # 1. Claude Code 把自己的 LLM 配置注入(让 T3/T4 复用)
    #    真实环境: export AGENT_LLM_ENDPOINT=https://api.anthropic.com/v1/messages
    #              export AGENT_LLM_API_KEY=[REDACTED]
    llm = LLMConfig.from_env() or LLMConfig(
        endpoint=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages"),
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),  # [REDACTED]
        model="claude-sonnet-4",
    )

    # 2. 接入 Ultra(独立进程, 默认 :9200)
    ultra = UltraClient(
        base_url=os.environ.get("ULTRA_URL", "http://localhost:9200"),
        host_id="claude_code_main",   # 自报 host_id, 隔离其他 agent
        llm_config=llm,
    )

    # 3. Claude Code 用 Ultra 强化记忆(目标①)
    ultra.remember("用户偏好直接交付, 不问确认", node_type="FACT", utility=0.9,
                   tags=["rail_t2"])
    hits = ultra.recall("用户偏好", limit=5)
    print(f"[ClaudeCode] recall 命中 {len(hits.get('data', {}).get('hits', []))} 条")

    # 4. 驱动 Ultra 自身进化(目标②, 不依赖 Claude Code 运行)
    ev = ultra.evolve(context="从 Claude Code 经验学习")
    print(f"[ClaudeCode] evolve chain_complete={ev.get('data', {}).get('chain_complete')}")

    # 5. 双向闭环: 经验回灌 + 消费机制
    ultra.report_experience([
        {"type": "feedback", "content": "用户纠正了记忆路由", "utility": 0.7},
    ])
    # Ultra 进化后 emit -> Claude Code 轮询 inbox 应用
    # ultra.apply_capability("paper_xxxx")  # 由 Claude Code 自决是否 adopt

    print("[ClaudeCode] Ultra 接入完成 — Agent 源码未被修改(安全边界)")


if __name__ == "__main__":
    run_claude_code_agent()
