"""LLM Bridge — 让 Ultra 调用外部 LLM（推理模型）用于四轨进化。

设计（HTTP 模式优先，符合 Ultra↔Hermes 集成架构）：
- 优先走 HTTP: POST 到 HERMES_LLM_ENDPOINT（OpenAI 兼容 /chat/completions 格式）
  —— 对应"HTTP 模式建桥"决策：Hermes 暴露端点，Ultra 经此调当前对话模型
- 兜底走本地 openai SDK（若设了 OPENAI_API_KEY / OPENAI_BASE_URL）
- 无 LLM 可用时 complete() 返回 None，调用方应降级为规则提取（不崩）

所有调用走超时保护，绝不阻塞进化主流程。
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)


class LLMBridge:
    """统一的 LLM 调用通道，供 T3/T4 进化轨使用。"""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        provider: str = "auto",
        timeout: float = 60.0,
    ):
        # HTTP 端点: Hermes 暴露的 /call_llm (OpenAI 兼容格式)
        self.endpoint = endpoint or os.environ.get("HERMES_LLM_ENDPOINT")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = os.environ.get("OPENAI_BASE_URL")  # 本地/openai 兼容
        self.model = model or os.environ.get("ULTRA_LLM_MODEL")  # None=复用对端默认模型
        self.provider = (provider or "auto").lower()
        self.timeout = timeout
        self._mode = self._detect_mode()
        logger.info("LLMBridge initialized (mode=%s, model=%s, provider=%s)", self._mode, self.model, self.provider)

    def _detect_mode(self) -> str:
        if self.endpoint:
            # 显式 anthropic/volc-ark provider -> 走 Anthropic /v1/messages 协议
            if self.provider in ("anthropic", "volc-ark", "volces", "ark"):
                return "anthropic"
            # endpoint 含 /v1/messages 或 anthropic 字样 -> anthropic 协议
            if "messages" in (self.endpoint or "") or "anthropic" in (self.endpoint or "").lower():
                return "anthropic"
            return "http"
        if self.api_key:
            return "local"
        return "none"

    @property
    def available(self) -> bool:
        return self._mode != "none"

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str | None:
        """调用 LLM 完成一次推理。无可用 LLM 时返回 None（调用方降级）。"""
        if self._mode == "http":
            return self._complete_http(prompt, system, temperature, max_tokens)
        if self._mode == "anthropic":
            return self._complete_anthropic(prompt, system, temperature, max_tokens)
        if self._mode == "local":
            return self._complete_local(prompt, system, temperature, max_tokens)
        logger.debug("LLMBridge: no LLM available, caller should degrade to rule-based")
        return None

    def _complete_anthropic(self, prompt, system, temperature, max_tokens) -> str | None:
        """Anthropic /v1/messages 协议 (火山 Ark coding / Claude 兼容端点).

        请求: POST {endpoint}  body={model,max_tokens,messages:[{role,content}]}
        鉴权: Authorization: Bearer <key>  (或 x-api-key + anthropic-version)
        响应: {content:[{type:'text',text:...} | {type:'thinking',thinking:...}]}
        """
        try:
            import httpx
            messages = []
            if system:
                # Anthropic 用独立 system 字段, 但部分兼容端点接受 messages 内 system role
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            payload = {
                "model": self.model or "glm-5.2",
                "max_tokens": max_tokens,
                "messages": messages,
                "temperature": temperature,
            }
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                # 火山 Ark coding 实测: Bearer 与 x-api-key 均接受
                headers["Authorization"] = f"Bearer {self.api_key}"
                headers["anthropic-version"] = "2023-06-01"
            resp = httpx.post(
                self.endpoint, json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            # 提取 text 块 (跳过 thinking)
            texts = []
            for block in data.get("content", []):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif block.get("type") == "thinking":
                    pass  # thinking 不计入输出
            return "\n".join(texts).strip() or None
        except Exception as e:
            logger.warning("LLMBridge Anthropic call failed: %s", e)
            return None

    def _complete_http(self, prompt, system, temperature, max_tokens) -> str | None:
        try:
            import httpx
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            payload = {
                "model": self.model or "default",
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            elif "HERMES" in (self.endpoint or "").upper() or "token" in os.environ:
                headers["Authorization"] = f"Bearer {os.environ.get('HERMES_TOKEN', '')}"
            resp = httpx.post(
                self.endpoint, json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning("LLMBridge HTTP call failed: %s", e)
            return None

    def _complete_local(self, prompt, system, temperature, max_tokens) -> str | None:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url or None)
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            resp = client.chat.completions.create(
                model=self.model or "gpt-4o-mini",
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self.timeout,
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.warning("LLMBridge local call failed: %s", e)
            return None
