"""Tests for api_server.py — API server module.

Target coverage increase from 26% to 70%+.
Tests cover all public methods including edge cases.
"""
import time
from collections import deque

import pytest

import socket
import urllib.error
import urllib.request

from fastapi.testclient import TestClient

from prometheus_nexus.services.api_server import (
    UltraAPIServer,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def server():
    """Create a default UltraAPIServer instance."""
    return UltraAPIServer()


@pytest.fixture
def server_with_config():
    """Create server with custom configuration."""
    return UltraAPIServer(host="0.0.0.0", port=8080)


# =============================================================================
# Test Initialization
# =============================================================================

class TestInit:
    """Test UltraAPIServer initialization."""

    def test_default_initialization(self):
        """Should initialize with default parameters."""
        server = UltraAPIServer()
        assert server is not None

    def test_custom_initialization(self):
        """Should accept custom parameters."""
        server = UltraAPIServer(host="localhost", port=9000)
        assert server.host == "localhost"
        assert server.port == 9000


# =============================================================================
# Test Start / Stop — 真实生命周期验证 (修复前为"假绿"测试)
# =============================================================================
# 旧 TestStart / TestStop 默认被 conftest 整体跳过(零覆盖), 启用时其断言为
# `assert isinstance(e, Exception)` 或 `except: pass`, 永不失败; 旧 TestEdgeCases
# 亦为假绿。它们既掩盖了 start() 就绪探测失败被静默吞掉(端口被占用仍报"已启动"),
# 也掩盖了 stop() 实际不会终止 uvicorn(只关 omega, HTTP 服务与端口仍存活)。
# 下列测试使用隔离空闲端口 + 真实断言, 真实验证启动→可达→is_running→停止→端口释放。

def _free_port() -> int:
    """分配一个当前空闲的 TCP 端口, 用于隔离测试避免与 9200 实例冲突。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestStart:
    """start() 必须真正拉起可达的服务并报告 is_running。"""

    def test_start_basic(self):
        port = _free_port()
        srv = UltraAPIServer(host="127.0.0.1", port=port)
        try:
            srv.start(background=True)
            # 真实信号 1: is_running 反映线程存活
            assert srv.is_running is True
            # 真实信号 2: 服务必须通过 HTTP 实际可达(而非仅不报错)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/v1/health", timeout=3
            ) as resp:
                assert resp.status == 200
        finally:
            srv.stop()
        # 停止后必须报告未运行
        assert srv.is_running is False

    def test_start_readiness_failure_is_loud(self, monkeypatch):
        """就绪探测失败时 start() 必须抛出, 而不是静默返回"成功"。"""
        port = _free_port()
        srv = UltraAPIServer(host="127.0.0.1", port=port)

        def _always_unreachable(*args, **kwargs):
            raise urllib.error.URLError("simulated: server never reachable")

        monkeypatch.setattr(urllib.request, "urlopen", _always_unreachable)
        with pytest.raises(RuntimeError):
            srv.start(background=True)
        # 清理: uvicorn 实际已绑定(探测被伪造), 必须能正常关停
        srv.stop()

    def test_start_twice_is_rejected(self):
        """重复 start() 不得双重绑定, 应显式拒绝。"""
        port = _free_port()
        srv = UltraAPIServer(host="127.0.0.1", port=port)
        try:
            srv.start(background=True)
            assert srv.is_running is True
            with pytest.raises(RuntimeError):
                srv.start(background=True)
        finally:
            srv.stop()


class TestStop:
    """stop() 必须真正终止服务并释放端口。"""

    def test_stop_terminates_server(self):
        port = _free_port()
        srv = UltraAPIServer(host="127.0.0.1", port=port)
        srv.start(background=True)
        assert srv.is_running is True
        srv.stop()
        assert srv.is_running is False
        # 端口必须释放: health 现在不可达
        with pytest.raises(urllib.error.URLError):
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/v1/health", timeout=2
            )

    def test_stop_when_not_running_is_safe(self):
        srv = UltraAPIServer(host="127.0.0.1", port=_free_port())
        srv.stop()  # 从未启动也必须安全
        assert srv.is_running is False


class TestEdgeCases:
    """边界输入必须被真实处理, 而非 except 吞掉。"""

    def test_invalid_port_stored(self):
        """构造函数必须保留传入的 port/host(契约), 而非静默丢弃。"""
        srv = UltraAPIServer(host="127.0.0.1", port=-1)
        assert srv.port == -1
        assert srv.host == "127.0.0.1"

    def test_large_port_stored(self):
        srv = UltraAPIServer(host="127.0.0.1", port=70000)
        assert srv.port == 70000

    def test_empty_host_stored(self):
        srv = UltraAPIServer(host="")
        assert srv.host == ""


# =============================================================================
# Test Health Endpoint — 监控盲区修复回归
# =============================================================================

class _FakeHealthStatus:
    """最小替身: 仅暴露 health 字段(路由实现只用 s.health)。"""
    def __init__(self, health: str):
        self.health = health


class _FakeOmega:
    """可控替身 Omega: 模拟不同引擎健康态, 或探测时抛异常。"""
    def __init__(self, health: str = "healthy", exc: Exception | None = None):
        self._health = health
        self._exc = exc

    def status(self):
        if self._exc is not None:
            raise self._exc
        return _FakeHealthStatus(self._health)


class TestHealthEndpointRealSignal:
    """GET /api/v1/health 必须暴露真实引擎健康, 而非硬编码 healthy。"""

    def test_healthy_engine_reports_real_health(self):
        srv = UltraAPIServer()
        srv.omega = _FakeOmega(health="healthy")
        body = TestClient(srv.app).get("/api/v1/health").json()
        assert body["status"] == "healthy"        # 存活契约保留
        assert body["engine_health"] == "healthy"  # 真实信号可见

    def test_degraded_engine_no_longer_masked_as_healthy(self):
        # 核心回归: 真实薄弱(degraded)不得被端点掩盖为 healthy
        srv = UltraAPIServer()
        srv.omega = _FakeOmega(health="degraded")
        body = TestClient(srv.app).get("/api/v1/health").json()
        assert body["status"] == "healthy"         # liveness 仍成立
        assert body["engine_health"] == "degraded"  # 真实降级态暴露

    def test_critical_engine_exposed(self):
        srv = UltraAPIServer()
        srv.omega = _FakeOmega(health="critical")
        body = TestClient(srv.app).get("/api/v1/health").json()
        assert body["engine_health"] == "critical"

    def test_missing_omega_reports_unhealthy(self):
        # 引擎未初始化 = 真实死亡, 看门狗应据此重启
        srv = UltraAPIServer()
        srv.omega = None
        body = TestClient(srv.app).get("/api/v1/health").json()
        assert body["status"] == "unhealthy"
        assert body["engine_health"] == "unavailable"

    def test_status_probe_failure_reports_unhealthy(self):
        srv = UltraAPIServer()
        srv.omega = _FakeOmega(exc=RuntimeError("engine dead"))
        body = TestClient(srv.app).get("/api/v1/health").json()
        assert body["status"] == "unhealthy"
        assert body["engine_health"] == "unknown"
        assert "status probe failed" in body["detail"]