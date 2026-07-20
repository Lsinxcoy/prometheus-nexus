"""HermesAdapter — HostAgentAdapter 的 Hermes 实现 (P1b, 解 B5).

把原 LLMBridge 的 Hermes 专属逻辑迁入 HostAgentAdapter 接口:
- llm_complete(): 复用 LLMBridge (HTTP 模式, 复用 Hermes 对话模型)
- emit_capability(): 把 Ultra 机制导出给 Hermes (经 HTTP 端点, 或降级为本地记录)
- ingest_experience(): 拉取 Hermes 运行时经验 (经 HTTP 端点, 无则降级)

env 名泛化:
- AGENT_LLM_ENDPOINT (通用, 优先)
- HERMES_LLM_ENDPOINT (Hermes 兼容别名, 保留)
"""
from __future__ import annotations

import logging
import os

from prometheus_nexus.integration.host_agent import HostAgentAdapter
from prometheus_nexus.integration.llm_bridge import LLMBridge

logger = logging.getLogger(__name__)


class HermesAdapter(HostAgentAdapter):
    """Hermes 宿主适配器. Ultra 通过它调用 Hermes 的 LLM 并把机制回流给 Hermes."""

    def __init__(self, endpoint: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: float = 60.0, host_id: str = "hermes",
                 provider: str = "auto"):
        # env 泛化: AGENT_LLM_ENDPOINT 优先, HERMES_LLM_ENDPOINT 兼容别名
        ep = endpoint or os.environ.get("AGENT_LLM_ENDPOINT") or os.environ.get("HERMES_LLM_ENDPOINT")
        self._bridge = LLMBridge(endpoint=ep, api_key=api_key, model=model, timeout=timeout,
                                 provider=provider)
        # Hermes 专用 emit 端点(可选): 把 capability 推给 Hermes
        self._emit_endpoint = os.environ.get("AGENT_CAPABILITY_ENDPOINT") or os.environ.get("HERMES_CAPABILITY_ENDPOINT")
        self.host_id = host_id  # [P2 C5] 多宿主隔离标识

    def llm_complete(self, prompt: str, system: str = "") -> str | None:
        return self._bridge.complete(prompt, system=system)

    def get_runtime_context(self) -> dict:
        """Hermes 运行时上下文. 有端点时尝试拉取, 无则返回基础信息."""
        if not self._bridge.available:
            return {"tools": [], "context_window": 0, "current_task": "", "host": "hermes", "llm": "none"}
        return {"tools": [], "context_window": 0, "current_task": "", "host": "hermes",
                "llm": self._bridge._mode, "endpoint": self._bridge.endpoint}

    def emit_capability(self, spec: dict) -> bool:
        """把 Ultra 进化机制导出给 Hermes.

        优先级:
        1. 有 AGENT_CAPABILITY_ENDPOINT -> HTTP POST(宿主实时接收)
        2. 无端点 -> 落本地 CapabilityInbox(宿主轮询/应用, 机制不丢) [P0 C1]
        """
        name = spec.get("name", "?")
        if self._emit_endpoint:
            try:
                import httpx
                resp = httpx.post(self._emit_endpoint, json=spec, timeout=self._bridge.timeout)
                ok = resp.status_code < 300
                logger.info("HermesAdapter: emit %s -> Hermes (%s)", name, "ok" if ok else resp.status_code)
                return ok
            except Exception as e:
                logger.debug("HermesAdapter: emit HTTP failed: %s", e)
        # 降级: 落本地 inbox(机制真接收, 不再射入虚空)
        try:
            from prometheus_nexus.integration.capability_inbox import CapabilityInbox
            inbox = CapabilityInbox()
            receipt = inbox.receive(spec)
            return receipt.accepted
        except Exception as e:
            logger.warning("HermesAdapter: emit fallback to inbox failed: %s", e)
            return False
    def ingest_experience(self, log: dict) -> None:
        """宿主经验回流. Hermes 侧无标准端点时, 由调用方(learn)直接喂 store, 此处 no-op."""
        logger.debug("HermesAdapter: ingest_experience (Hermes 经 learn(source=host_experience) 直喂 store)")

    def pull_experience(self, limit: int = 10) -> list[dict]:
        """拉取宿主运行时经验 [P0 C2 真拉取].

        协议: 宿主把经验写到 AGENT_EXPERIENCE_FILE(默认 archive/host_experience.json)
        每行一个 JSON 事件 {type, content, utility, timestamp}. Ultra learn 读取并路由进燃料.
        无文件返回空 list(不崩).
        """
        import json
        path = os.environ.get("AGENT_EXPERIENCE_FILE") or "archive/host_experience.json"
        if not os.path.exists(path):
            return []
        out = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
                    if len(out) >= limit:
                        break
        except Exception as e:
            logger.debug("HermesAdapter: pull_experience failed: %s", e)
        return out

    def apply_capability(self, name: str, host_id: str = "hermes") -> bool:
        """宿主侧应用机制(生成 applied 描述文件, 供 Hermes 生成 tool/prompt). [P0 C1]"""
        try:
            from prometheus_nexus.integration.capability_inbox import CapabilityInbox
            inbox = CapabilityInbox()
            r = inbox.apply_capability(name, host_id=host_id)
            return r.applied
        except Exception as e:
            logger.debug("HermesAdapter: apply_capability failed: %s", e)
            return False
