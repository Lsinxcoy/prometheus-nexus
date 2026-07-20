"""UltraClient — Agent 侧官方 SDK [V3.3 G4].

让任意 Agent 用最少代码接入 Ultra 独立进程, 调用所有机制+工具:
- remember / recall (超级记忆强化①)
- evolve / ruminate (驱动 Ultra 自身进化②)
- compile_mechanism (T4, 复用 Agent LLM) / extract_mechanism (T3)
- report_experience (经验回灌, 让 Ultra 进化) / apply_capability (消费 Ultra 产出)

Agent 永不被动改源码: Ultra 只经 emit_capability 给"建议", Agent apply_capability 自决.
"""
from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False
    logger.warning("UltraClient: httpx 不可用, 请 pip install httpx")


@dataclass
class LLMConfig:
    """Agent LLM 配置(注入 Ultra 复用 T3/T4). [REDACTED] api_key 仅内存."""
    endpoint: str
    api_key: str = ""          # [REDACTED] 不持久化
    model: str = ""
    provider: str = "auto"

    @classmethod
    def from_env(cls) -> Optional["LLMConfig"]:
        ep = os.environ.get("AGENT_LLM_ENDPOINT") or os.environ.get("HERMES_LLM_ENDPOINT")
        if not ep:
            return None
        return cls(endpoint=ep, api_key=os.environ.get("AGENT_LLM_API_KEY", ""),
                   model=os.environ.get("AGENT_LLM_MODEL", ""),
                   provider=os.environ.get("AGENT_LLM_PROVIDER", "auto"))

    def export_env(self) -> dict:
        """导出为环境变量(启动 Ultra 进程时注入)."""
        env = {"AGENT_LLM_ENDPOINT": self.endpoint}
        if self.api_key:
            env["AGENT_LLM_API_KEY"] = self.api_key       # [REDACTED] 仅内存传递
        if self.model:
            env["AGENT_LLM_MODEL"] = self.model
        if self.provider != "auto":
            env["AGENT_LLM_PROVIDER"] = self.provider
        return env


class UltraClient:
    """Agent 接入 Ultra 的官方客户端."""

    def __init__(self, base_url: str = "http://localhost:9200", host_id: str = "agent_default",
                 llm_config: Optional[LLMConfig] = None, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.host_id = host_id
        self.llm = llm_config
        self.timeout = timeout
        if not _HAS_HTTPX:
            raise RuntimeError("UltraClient 需要 httpx")

    # ── 记忆层(强化①) ──
    def remember(self, content: str, node_type: str = "FACT", utility: float = 0.5,
                 tags: Optional[list] = None, **kw) -> dict:
        return self._post("/api/v1/remember", {
            "content": content, "node_type": node_type, "utility": utility,
            "tags": tags or [], **kw})

    def recall(self, query: str, limit: int = 10, future_aware: bool = True, **kw) -> dict:
        return self._post("/api/v1/recall", {
            "query": query, "limit": limit, "future_aware": future_aware, **kw})

    def search(self, query: str, limit: int = 10) -> dict:
        return self._post("/api/v1/nodes/search", {"query": query, "limit": limit})

    # ── 进化层(驱动 Ultra 自身进化②) ──
    def evolve(self, context: str = "") -> dict:
        """进化并返回链完整性追踪."""
        return self._post("/api/v1/evolve/chain", {"context": context})

    def ruminate(self, mode: str = "full", force: bool = True) -> dict:
        return self._post("/api/v1/ruminate", {"mode": mode, "force": force})

    # ── 机制层(全机制调用) ──
    def list_mechanisms(self) -> dict:
        return self._get("/api/v1/mechanisms")

    def invoke_mechanism(self, name: str, context: dict | None = None, effect: float | None = None) -> dict:
        req = {"name": name, "context": context or {}}
        if effect is not None:
            req["effect"] = effect
        return self._post("/api/v1/mechanisms/invoke", req)

    def compile_mechanism(self, arxiv_id: str = "", title: str = "") -> dict:
        """T4 编译(复用 Agent LLM)."""
        return self._post("/api/v1/t4/compile", {"arxiv_id": arxiv_id, "title": title})

    def extract_mechanism(self, source: str = "github", query: str = "") -> dict:
        """T3 提取(复用 Agent LLM)."""
        return self._post("/api/v1/t3/extract", {"source": source, "query": query})

    # ── 双向闭环 ──
    def report_experience(self, events: list[dict]) -> None:
        """Agent 运行时经验回灌 Ultra(让 Ultra 进化). 写本地经验文件, Ultra 经 pull_experience 消费."""
        path = os.environ.get("AGENT_EXPERIENCE_FILE", "archive/host_experience.json")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for ev in events:
                ev.setdefault("host_id", self.host_id)
                ev.setdefault("timestamp", __import__("time").time())
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    def apply_capability(self, name: str) -> bool:
        """消费 Ultra 进化出的机制(宿主自决, 不改 agent 源码)."""
        # 经 inbox 应用(对应 GenericAgentAdapter.apply_capability)
        try:
            from prometheus_nexus.integration.capability_inbox import CapabilityInbox
            return CapabilityInbox().apply_capability(name, host_id=self.host_id).applied
        except Exception as e:
            logger.debug("apply_capability failed: %s", e)
            return False

    def utility_report(self) -> dict:
        return self._get("/api/v1/utility/report")

    def health(self) -> dict:
        return self._get("/api/v1/health")

    # ── HTTP 底层 ──
    def _post(self, path: str, payload: dict) -> dict:
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.post(self.base_url + path, json=payload)
                return r.json()
        except Exception as e:
            logger.error("UltraClient POST %s failed: %s", path, e)
            return {"success": False, "error": str(e)}

    def _get(self, path: str) -> dict:
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.get(self.base_url + path)
                return r.json()
        except Exception as e:
            logger.error("UltraClient GET %s failed: %s", path, e)
            return {"success": False, "error": str(e)}
