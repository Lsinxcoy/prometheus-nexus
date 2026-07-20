"""Agent 接入示例: AutoGPT.

展示 AutoGPT(自主体 agent)如何作为 Ultra 的宿主, 经 UltraClient 接入。
与 Claude Code 示例同构 — 证明接入协议对"任意 agent"通用(非 Hermes 专属)。

运行: 设好 AGENT_LLM_ENDPOINT 后 `python examples/autogpt_agent.py`
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.client import UltraClient, LLMConfig


def run_autogpt_agent():
    # AutoGPT 的 LLM 配置(注入 Ultra 复用 T3/T4)
    llm = LLMConfig.from_env() or LLMConfig(
        endpoint=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"),
        api_key=os.environ.get("OPENAI_API_KEY", ""),  # [REDACTED]
        model="gpt-4o",
    )

    ultra = UltraClient(
        base_url=os.environ.get("ULTRA_URL", "http://localhost:9200"),
        host_id="autogpt_agent_01",
        llm_config=llm,
    )

    # 自主循环: AutoGPT 每轮用 Ultra 记忆 + 驱动进化
    ultra.remember("AutoGPT 任务: 自动化数据分析", node_type="PROCEDURE", utility=0.8,
                   tags=["rail_t1"])
    hits = ultra.recall("自动化 数据分析", limit=5)
    print(f"[AutoGPT] recall 命中 {len(hits.get('data', {}).get('hits', []))} 条")

    # 编译机制(T4 复用 AutoGPT 的 LLM)
    # comp = ultra.compile_mechanism(arxiv_id="2401.12345")  # 需有效 LLM endpoint

    # 驱动 Ultra 进化
    ev = ultra.evolve(context="AutoGPT 自主进化")
    print(f"[AutoGPT] evolve chain_complete={ev.get('data', {}).get('chain_complete')}")

    # 经验回灌(让 Ultra 更强 -> AutoGPT 下次消费更强产出)
    ultra.report_experience([
        {"type": "task_result", "content": "完成数据分析任务", "utility": 0.9},
    ])

    print("[AutoGPT] Ultra 接入完成 — 复用 AutoGPT LLM 编译机制, Agent 源码零修改")


if __name__ == "__main__":
    run_autogpt_agent()
