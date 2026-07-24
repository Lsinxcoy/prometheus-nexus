"""Tests for Omega.start_metrics_server — /metrics HTTP 端点.

验证意图(高风险遥测项完整形态):
1. start_metrics_server 启动 daemon 线程监听 127.0.0.1:port
2. HTTP GET /metrics 返回 200 + Prometheus text(含 omega_system_ / omega_mechanism_)
3. close() 优雅停止 server(端口释放)
"""

from __future__ import annotations

import socket
import time
import urllib.request

import pytest

from prometheus_nexus.foundation.schema import ZConfig
from prometheus_nexus.life import Omega


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def omega():
    o = Omega(ZConfig(database_path=":memory:"))
    yield o
    o.close()


def test_metrics_server_serves_prometheus(omega: Omega):
    port = _free_port()
    omega.start_metrics_server(port=port, host="127.0.0.1")
    try:
        time.sleep(0.2)  # 等线程起来
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        assert "# TYPE" in body
        assert "omega_system_node_count" in body
    finally:
        omega.stop_metrics_server()


def test_metrics_server_close_releases_port(omega: Omega):
    port = _free_port()
    omega.start_metrics_server(port=port, host="127.0.0.1")
    time.sleep(0.2)
    omega.close()  # 调 stop_metrics_server
    # 端口应被释放(可重新绑定)
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        reused = True
    except OSError:
        reused = False
    finally:
        s.close()
    assert reused is True
