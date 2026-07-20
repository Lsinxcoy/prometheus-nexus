"""V3.5a 真实 LLM 端到端验证 T4 真编译.

目的: 证明当 Agent 提供有效 AGENT_LLM_ENDPOINT 时, T4(mechanism_compiler.compile)
       真调用 LLM 并解析出 draft_code(含 BaseMechanism 子类), 而非占位降级.

方法(诚实):
- 起本地 mock OpenAI-compatible HTTP server 作为 AGENT_LLM_ENDPOINT(返回合法
  chat completion 格式, 含 Python draft_code). 这是真实 HTTP 调用(非内存 mock).
- monkeypatch fetch_arxiv_fulltext 返回固定全文(本环境无 arxiv 网络, 标准测试桩).
- 验证 T4 编译链路: LLM 调用 -> 响应解析 -> draft_code 生成(真编译非占位).
"""
import sys
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/src")

import os
import json
import time
import tempfile
import threading
import http.server
from functools import partial

import pytest


# ── 本地 mock OpenAI-compatible LLM server ──
def _make_llm_handler(factory):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            try:
                req = json.loads(body)
            except Exception:
                req = {}
            # 生成一段真实 draft_code(模拟 LLM 编译产出)
            draft = (
                "from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism\n\n"
                "class compiled_real_mech(BaseMechanism):\n"
                "    name = 'compiled_real_mech'\n"
                "    category = 'compiled'\n\n"
                "    def run(self, context=None):\n"
                "        # 真实编译产物: 论文机制被 LLM 提取为可执行代码\n"
                "        return {'ok': True, 'compiled_by': 'real_llm', 'context': context}\n"
            )
            resp = {
                "choices": [{"message": {"role": "assistant", "content": draft}}],
                "model": req.get("model", "mock"),
            }
            data = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass  # 静默

    return Handler


def _start_llm_server(port: int):
    handler = _make_llm_handler(None)
    srv = http.server.HTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


@pytest.fixture
def llm_server():
    port = 0
    srv = None
    # 找空闲端口
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = _start_llm_server(port)
    yield f"http://127.0.0.1:{port}/v1/chat/completions"
    srv.shutdown()


class TestRealLLMT4Compile:
    def test_t4_compiles_real_draft_with_agent_llm(self, llm_server):
        """Agent 注入 LLM 后, T4 真编译出 draft_code(非占位)."""
        from prometheus_nexus.life import Omega
        from prometheus_nexus.mechanisms import mechanism_compiler as mc_mod

        old = dict(os.environ)
        db = os.path.join(tempfile.gettempdir(), f"ultra_t4_{os.getpid()}_{id(object())}.db")
        o = None
        try:
            os.environ["AGENT_LLM_ENDPOINT"] = llm_server
            os.environ.pop("AGENT_LLM_API_KEY", None)
            # 桩: 无 arxiv 网络, mock 全文(标准测试隔离, 不改动生产代码)
            orig_fetch = mc_mod.fetch_arxiv_fulltext
            mc_mod.fetch_arxiv_fulltext = lambda aid: (
                "We propose a novel caching mechanism. Our method improves recall latency. "
                "Algorithm 1 describes the procedure. Our approach uses overlap fusion."
            )
            # Omega 应注入 Agent LLM
            o = Omega(db_path=db)
            assert o.llm is not None and o.llm.available, "Agent LLM 应被注入"

            # T4 真实编译
            mech = o.mechanism_compiler.compile("2401.12345", paper_title="Test Paper")
            assert mech is not None, "T4 应编译出机制(LLM 可用)"
            draft = mech.draft_code or ""
            # 关键断言: 真编译产物含 BaseMechanism 子类(非占位降级)
            assert "BaseMechanism" in draft, "draft_code 应含真实机制代码"
            assert "compiled_real_mech" in draft, "draft_code 应含 LLM 生成的类名"
            assert "awaiting LLM/human implementation" not in draft, "不应是占位降级"
        finally:
            os.environ.clear(); os.environ.update(old)
            if o: o.store.close()
            try: os.remove(db)
            except Exception: pass
            mc_mod.fetch_arxiv_fulltext = orig_fetch

    def test_t4_falls_back_to_placeholder_without_llm(self, monkeypatch):
        """无 Agent LLM 时, T4 降级占位(诚实: 明确标记 await 实现, 非伪装成功)."""
        from prometheus_nexus.life import Omega
        from prometheus_nexus.mechanisms import mechanism_compiler as mc_mod
        from prometheus_nexus.integration.llm_config import LLMConfig

        # V3.7: 无 env 时 from_hermes() 会自动读 ~/.hermes/config.yaml 的 model 段.
        #   本测试模拟"无 LLM 配置"环境 -> mock from_hermes 返回 None
        #   (否则 CI/本机有 config.yaml 真实 key 时, o.llm.available 会为 True, 断言失效).
        monkeypatch.setattr(LLMConfig, "from_hermes", classmethod(lambda cls: None))
        old = dict(os.environ)
        db = os.path.join(tempfile.gettempdir(), f"ultra_t4b_{os.getpid()}_{id(object())}.db")
        o = None
        try:
            os.environ.pop("AGENT_LLM_ENDPOINT", None)
            os.environ.pop("HERMES_LLM_ENDPOINT", None)
            orig_fetch = mc_mod.fetch_arxiv_fulltext
            mc_mod.fetch_arxiv_fulltext = lambda aid: "We propose a caching method. Our approach uses fusion."
            o = Omega(db_path=db)
            assert not o.llm.available, "无 LLM 时应降级"
            mech = o.mechanism_compiler.compile("2401.99999", paper_title="No LLM")
            assert mech is not None
            # 占位降级: 明确标记 awaiting implementation
            assert "awaiting LLM/human implementation" in (mech.draft_code or ""), "无 LLM 应占位标记"
        finally:
            os.environ.clear(); os.environ.update(old)
            if o: o.store.close()
            try: os.remove(db)
            except Exception: pass
            mc_mod.fetch_arxiv_fulltext = orig_fetch
