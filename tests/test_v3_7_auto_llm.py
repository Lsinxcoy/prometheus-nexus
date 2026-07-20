"""V3.7 自动复用 Hermes LLM 配置(与代理解耦).

验证: Omega 启动时自动探测并复用宿主 Agent(Hermes) 的 LLM 配置,
不依赖人工注入 endpoint, 与网络代理(clash等)完全无关.

探测优先级(LLMConfig.from_hermes):
  env(AGENT_LLM_*) > hermes config.yaml model 段 > 探测端口 > None(T4 诚实降级)
"""
import sys
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/src")

import os
import json
import tempfile
import pytest


@pytest.fixture
def clean_env():
    old = dict(os.environ)
    for k in ("AGENT_LLM_ENDPOINT", "HERMES_LLM_ENDPOINT", "AGENT_LLM_API_KEY",
               "AGENT_LLM_MODEL", "AGENT_LLM_PROVIDER"):
        os.environ.pop(k, None)
    yield
    os.environ.clear(); os.environ.update(old)


class TestAutoReuseHermesLLM:
    def test_env_overrides_all(self, clean_env, monkeypatch):
        """env 注入优先于一切(人工覆盖)."""
        from prometheus_nexus.integration.llm_config import LLMConfig
        monkeypatch.setenv("AGENT_LLM_ENDPOINT", "http://env.example.com/v1/chat")
        cfg = LLMConfig.from_hermes()
        assert cfg is not None
        assert cfg.endpoint == "http://env.example.com/v1/chat"
        assert cfg.available is True

    def test_reads_hermes_config_yaml(self, clean_env, monkeypatch, tmp_path):
        """自动读 ~/.hermes/config.yaml 的 model 段(持久化配置)."""
        from prometheus_nexus.integration.llm_config import LLMConfig
        # 伪造 hermes config.yaml
        cfg_dir = tmp_path / ".hermes"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text(
            "model:\n  base_url: http://hermes-local:11434/v1/chat/completions\n"
            "  api_key: sk-test\n  default: claude-sonnet-4\n  provider: anthropic\n",
            encoding="utf-8")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        # expanduser('~') 在 WIN 上指向 USERPROFILE
        monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path) if p == "~" else p)
        cfg = LLMConfig.from_hermes()
        assert cfg is not None, "应自动从 hermes config.yaml 读到 model 段"
        assert "hermes-local:11434" in cfg.endpoint
        assert cfg.api_key == "sk-test"
        assert cfg.model == "claude-sonnet-4"

    def test_nous_provider_auto_read(self, clean_env, monkeypatch, tmp_path):
        """V3.7b: provider=nous 时自动读 config.yaml model 段(即使无 api_key)."""
        from prometheus_nexus.integration.llm_config import LLMConfig
        cfg_dir = tmp_path / ".hermes"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text(
            "model:\n  base_url: https://inference-api.nousresearch.com/v1\n"
            "  default: tencent/hunyuan-hy3:free\n  provider: nous\n",
            encoding="utf-8")
        monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path) if p == "~" else p)
        cfg = LLMConfig.from_hermes()
        assert cfg is not None
        assert "inference-api.nousresearch.com" in cfg.endpoint
        assert cfg.provider == "nous"
        assert cfg.model == "tencent/hunyuan-hy3:free"
        assert cfg.available is True  # endpoint 非空即可用(即使 OAuth 需本地代理)

    def test_no_config_returns_none_honest_degrade(self, clean_env, monkeypatch, tmp_path):
        """无任何 LLM 配置 -> None (T4 诚实降级, 非崩溃, 非 NullHost 丢宿主)."""
        from prometheus_nexus.integration.llm_config import LLMConfig
        monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path) if p == "~" else p)
        cfg = LLMConfig.from_hermes()
        assert cfg is None, "无配置应返回 None, 由 Omega 走 HermesAdapter 宿主身份 + T4 降级"

    def test_omega_auto_applies_hermes_llm(self, clean_env, monkeypatch, tmp_path):
        """Omega 启动时自动把 Hermes LLM 配置注入 self.llm (host=HermesAdapter)."""
        from prometheus_nexus.life import Omega
        # 伪造 hermes config.yaml 含 model 段
        cfg_dir = tmp_path / ".hermes"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text(
            "model:\n  base_url: http://auto-injected:9999/v1/chat\n  api_key: sk-auto\n  default: gpt-auto\n",
            encoding="utf-8")
        monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path) if p == "~" else p)
        db = os.path.join(tempfile.gettempdir(), f"omega_auto_{os.getpid()}_{id(object())}.db")
        o = None
        try:
            o = Omega(db_path=db)
            # 宿主身份应仍是 Hermes (非 NullHost)
            assert o.host.__class__.__name__ == "HermesAdapter", "应自动以 Hermes 宿主身份"
            # LLM 应自动从 hermes config 注入
            assert o.llm is not None, "Omega 应自动注入 Hermes LLM 配置"
            assert "auto-injected:9999" in o.llm.endpoint
        finally:
            if o: o.store.close()
            try: os.remove(db)
            except Exception: pass
