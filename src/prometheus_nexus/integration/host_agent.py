"""HostAgentAdapter — 宿主 agent 抽象层 (P1a, 解 B5/B6/B7).

设计动机(实测证据):
- 原 LLMBridge 把宿主焊成 Hermes (env 名 HERMES_LLM_ENDPOINT, 注释/Bearer 逻辑 Hermes 专属)
- T4 激活机制零回流宿主 (grep emit_capability|to_host 全空)
- learn() 燃料源仅 ScanSource(web/arxiv/github), 无宿主运行时经验源

本抽象让 Ultra 成为"任意 agent 的外挂记忆 + 自进化生命体":
- llm_complete():      宿主的推理入口 (Hermes 走 HTTP, Claude Code 走 SDK, 自研走自己的)
- get_runtime_context(): 宿主的上下文窗口/工具清单/当前任务
- emit_capability():    把 Ultra 进化出的机制导出成宿主可用的能力(tool/prompt/检索策略)
- ingest_experience():   宿主运行时经验(行为日志/失败/反馈)回流进 Ultra 进化燃料

任意宿主只需实现一个 Adapter, 即可即插即用 — Ultra 内核不感知具体宿主.
"""
from __future__ import annotations
import abc
import logging
import os

logger = logging.getLogger(__name__)

from prometheus_nexus.integration.llm_bridge import LLMBridge


class HostAgentAdapter(abc.ABC):
    """宿主 agent 抽象接口. 所有具体宿主(Hermes/Claude Code/AutoGPT/自研)实现此接口."""

    def _mark_consumed(self, name: str) -> None:
        """机制被宿主消费(emit/apply) → 沉淀消费标记进 MechanismRegistry.

        D1+B1 联动: AR 经事件记 fitness 趋势(瞬时), 此处把消费沉淀进
        registry._mechanisms[name]['consumed_at'] (持久), 使 _compute_fitness
        的 consumption_score 维度(consumed/total) 从死维度变活维度。
        Omega 经 D1 反向持有(self._omega) 可访问 registry; 无则静默跳过。
        """
        try:
            omega = getattr(self, "_omega", None)
            if omega is None:
                return
            reg = getattr(omega, "mechanism_registry", None)
            if reg is None:
                return
            mechs = getattr(reg, "_mechanisms", None) or {}
            entry = mechs.get(name)
            if isinstance(entry, dict):
                entry["consumed_at"] = __import__("time").time()
                # 持久化消费标记 (解 registry 纯内存、重启丢根因)
                try:
                    reg._persist()
                except Exception:
                    pass
        except Exception as e:
            logger.debug("HostAgentAdapter._mark_consumed(%s) failed: %s", name, e)

    # 多宿主隔离标识 [P2 C5]: 同一 Ultra 服务多个 agent 时, 经验/机制按 host_id 分区
    host_id: str = "default"

    @abc.abstractmethod
    def llm_complete(self, prompt: str, system: str = "") -> str | None:
        """调用宿主的 LLM 完成一次推理. 无可用时返回 None (调用方降级)."""

    @abc.abstractmethod
    def get_runtime_context(self) -> dict:
        """返回宿主运行时上下文: {tools: [...], context_window: int, current_task: str, ...}."""

    @abc.abstractmethod
    def emit_capability(self, spec: dict) -> bool:
        """把 Ultra 进化出的机制导出给宿主.

        spec 结构: {
            "name": 机制名,
            "target_location": {module, lineno, symbol, ...} (来自 P7 行为定位),
            "draft_code": 机制草案,
            "claim": 机制描述,
            "category": "compiled"(T4) / "extracted"(T3),
        }
        返回 True 表示宿主成功接收(宿主可据此生成 tool/prompt/检索策略).
        注意: 这是"建议+宿主确认"语义, 不自动直替宿主生产 (对齐 P6 原则).
        """

    @abc.abstractmethod
    def ingest_experience(self, log: dict) -> None:
        """宿主运行时经验回流进 Ultra 进化燃料.

        log 结构: {source: "host_experience", events: [{type, content, utility, timestamp}], ...}
        Ultra 的 learn() 会消费它, 经 rumination 路由到 T2/T4 燃料 (复用 rail_t1~t4).
        """

    @abc.abstractmethod
    def pull_experience(self, limit: int = 10) -> list[dict]:
        """拉取宿主运行时经验(供 Ultra learn 消费). 与 ingest 反向: Ultra 主动拉.

        返回事件列表: [{type, content, utility, timestamp}, ...]
        宿主可把经验写到本地文件/队列, 此方法读取. 无经验返回空 list(不崩).
        """

    @abc.abstractmethod
    def apply_capability(self, name: str, host_id: str = "default") -> bool:
        """宿主侧应用 Ultra 推送的机制(生成可执行的机制描述, 供宿主生成 tool/prompt).

        返回 True 表示机制已落地(能真正增强宿主能力), 而非仅日志.
        这是"建议+宿主确认"语义的终点: Ultra emit -> 宿主 apply -> 能力生效.
        """


class NullHostAdapter(HostAgentAdapter):
    """空宿主适配器: 无宿主时(如独立运行/测试)的安全降级.

    所有方法 no-op 或返回空 — 保证 Ultra 在无宿主环境下仍能自进化
    (机制注册进 registry 但不回流宿主, 不退化为崩溃).
    """
    host_id = "none"

    def llm_complete(self, prompt: str, system: str = "") -> str | None:
        return None

    def get_runtime_context(self) -> dict:
        return {"tools": [], "context_window": 0, "current_task": "", "host": "none"}

    def emit_capability(self, spec: dict) -> bool:
        logger.debug("NullHostAdapter: emit_capability -> inbox (no live host): %s", spec.get("name"))
        # P0 C1: 无宿主时也落 inbox, 机制不丢(只是无宿主实时接收)
        name = spec.get("name", "?")
        try:
            from prometheus_nexus.integration.capability_inbox import CapabilityInbox
            accepted = CapabilityInbox().receive(spec).accepted
            try:
                bus = getattr(self, "_omega", None)
                if bus is not None and hasattr(bus, "event_bus"):
                    bus.event_bus.publish({"type": "capability_consumed", "data": {"name": name, "action": "emit", "accepted": bool(accepted)}})
                    self._mark_consumed(name)
            except Exception:
                pass
            return accepted
        except Exception:
            return False

    def ingest_experience(self, log: dict) -> None:
        logger.debug("NullHostAdapter: ingest_experience no-op (no host)")

    def pull_experience(self, limit: int = 10) -> list[dict]:
        return []  # 无宿主时无经验

    def apply_capability(self, name: str, host_id: str = "default") -> bool:
        # 无宿主时仍生成 applied 描述文件(机制落地为产物, 待宿主接入时可用)
        try:
            from prometheus_nexus.integration.capability_inbox import CapabilityInbox
            applied = CapabilityInbox().apply_capability(name, host_id=host_id).applied
            try:
                bus = getattr(self, "_omega", None)
                if bus is not None and hasattr(bus, "event_bus"):
                    bus.event_bus.publish({"type": "capability_consumed", "data": {"name": name, "action": "apply", "accepted": bool(applied)}})
                    self._mark_consumed(name)
            except Exception:
                pass
            return applied
        except Exception:
            return False


class GenericAgentAdapter(HostAgentAdapter):
    """任意 agent 的通用适配器 [V3.1 G3].

    与 HermesAdapter 逻辑相同(复用 LLMBridge + CapabilityInbox + 经验文件协议),
    但 host_id 由 agent 自报, 不默认 "hermes" — 实现真正多 agent 隔离接入.

    用法:
        adapter = GenericAgentAdapter(host_id="claude_code_abc",
                                      llm_config=LLMConfig.from_env())
        omega = Omega(host=adapter)   # 或 Omega() 后 omega.host = adapter
    """

    def __init__(self, host_id: str, endpoint: str | None = None,
                 api_key: str | None = None, model: str | None = None,
                 capability_endpoint: str | None = None, timeout: float = 60.0):
        # host_id 由 agent 自报(关键: 不默认 hermes)
        self.host_id = host_id
        ep = endpoint or os.environ.get("AGENT_LLM_ENDPOINT") or os.environ.get("HERMES_LLM_ENDPOINT")
        self._bridge = LLMBridge(endpoint=ep, api_key=api_key, model=model, timeout=timeout)
        self._emit_endpoint = capability_endpoint or os.environ.get("AGENT_CAPABILITY_ENDPOINT") \
            or os.environ.get("HERMES_CAPABILITY_ENDPOINT")

    def llm_complete(self, prompt: str, system: str = "") -> str | None:
        return self._bridge.complete(prompt, system=system)

    def get_runtime_context(self) -> dict:
        if not self._bridge.available:
            return {"tools": [], "context_window": 0, "current_task": "",
                    "host": self.host_id, "llm": "none"}
        return {"tools": [], "context_window": 0, "current_task": "",
                "host": self.host_id, "llm": self._bridge._mode,
                "endpoint": self._bridge.endpoint}

    def emit_capability(self, spec: dict) -> bool:
        """导出机制给 agent. 有端点 HTTP POST, 无则落 inbox(机制不丢)."""
        name = spec.get("name", "?")
        if self._emit_endpoint:
            try:
                import httpx
                resp = httpx.post(self._emit_endpoint, json=spec, timeout=self._bridge.timeout)
                ok = resp.status_code < 300
                logger.info("GenericAgentAdapter[%s]: emit %s -> %s", self.host_id, name,
                            "ok" if ok else resp.status_code)
                try:
                    bus = getattr(self, "_omega", None)
                    if bus is not None and hasattr(bus, "event_bus"):
                        bus.event_bus.publish({"type": "capability_consumed", "data": {"name": name, "action": "emit", "accepted": True}})
                    self._mark_consumed(name)
                except Exception:
                    pass
                return ok
            except Exception as e:
                logger.debug("GenericAgentAdapter[%s]: emit HTTP failed: %s", self.host_id, e)
        try:
            from prometheus_nexus.integration.capability_inbox import CapabilityInbox
            accepted = CapabilityInbox().receive(spec).accepted
            try:
                bus = getattr(self, "_omega", None)
                if bus is not None and hasattr(bus, "event_bus"):
                    bus.event_bus.publish({"type": "capability_consumed", "data": {"name": name, "action": "emit", "accepted": bool(accepted)}})
                    self._mark_consumed(name)
            except Exception:
                pass
            return accepted
        except Exception as e:
            logger.warning("GenericAgentAdapter[%s]: emit inbox failed: %s", self.host_id, e)
            return False

    def ingest_experience(self, log: dict) -> None:
        logger.debug("GenericAgentAdapter[%s]: ingest_experience (经 learn 直喂 store)", self.host_id)

    def pull_experience(self, limit: int = 10) -> list[dict]:
        """拉取 agent 运行时经验(同 HermesAdapter 协议: AGENT_EXPERIENCE_FILE)."""
        import json
        import os
        path = os.environ.get("AGENT_EXPERIENCE_FILE", "archive/host_experience.json")
        if not os.path.exists(path):
            return []
        try:
            out = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                    if len(out) >= limit:
                        break
            return out
        except Exception as e:
            logger.debug("GenericAgentAdapter[%s]: pull_experience failed: %s", self.host_id, e)
            return []

    def apply_capability(self, name: str, host_id: str = "default") -> bool:
        try:
            from prometheus_nexus.integration.capability_inbox import CapabilityInbox
            applied = CapabilityInbox().apply_capability(name, host_id=self.host_id).applied
            try:
                bus = getattr(self, "_omega", None)
                if bus is not None and hasattr(bus, "event_bus"):
                    bus.event_bus.publish({"type": "capability_consumed", "data": {"name": name, "action": "apply", "accepted": bool(applied)}})
                    self._mark_consumed(name)
            except Exception:
                pass
            return applied
        except Exception:
            return False
