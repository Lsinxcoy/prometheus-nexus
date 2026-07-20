"""V3.6 Dashboard 升级验证.

验证: 高级 dashboard 的聚合端点 + 静态资源 + HTML 引用正确.
- /api/v1/dashboard/summary 返回机制/进化/记忆/宿主/论文全维度
- /api/v1/dashboard/static/dashboard.css + dashboard.js 可访问
- /dashboard 返回新 HTML(引用 static 资源)
"""
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
import pytest

PY = os.environ.get("ULTRA_PY", r"E:/Prometheus Nexus/.venv/Scripts/python.exe")
SRC = r"E:/Prometheus Nexus/src"


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _wait(url, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1); return True
        except Exception:
            time.sleep(0.3)
    return False


@pytest.fixture
def srv():
    port = _free_port()
    db = os.path.join(tempfile.gettempdir(), f"ultra_dash_{os.getpid()}_{int(time.time()*1000)}.db")
    env = dict(os.environ); env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.Popen([PY, "-m", "prometheus_nexus.services.api_server",
                          "--host", "127.0.0.1", "--port", str(port), "--db-path", db],
                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        assert _wait(f"{base}/api/v1/health", 30)
        yield base
    finally:
        p.terminate()
        try: p.wait(timeout=10)
        except Exception: p.kill()
        try: os.remove(db)
        except Exception: pass


class TestDashboardV36:
    def test_summary_endpoint_full(self, srv):
        import json
        raw = urllib.request.urlopen(f"{srv}/api/v1/dashboard/summary", timeout=5).read()
        d = json.loads(raw)
        assert d["success"] is True
        data = d["data"]
        # 五大维度齐全
        assert "mechanisms" in data and "evolution" in data and "memory" in data
        assert "agents" in data and "papers" in data
        # 论文六篇映射
        assert len(data["papers"]) == 6
        # 机制层字段
        assert "status_dist" in data["mechanisms"]
        assert "superposed" in data["mechanisms"]

    def test_static_assets_served(self, srv):
        import json
        # css
        r1 = urllib.request.urlopen(f"{srv}/api/v1/dashboard/static/dashboard.css", timeout=5)
        assert r1.status == 200 and "text/css" in r1.headers.get("Content-Type", "")
        # js
        r2 = urllib.request.urlopen(f"{srv}/api/v1/dashboard/static/dashboard.js", timeout=5)
        assert r2.status == 200
        body = r2.read().decode("utf-8", "ignore")
        assert "updateAll" in body  # JS 含渲染逻辑

    def test_dashboard_html_references_static(self, srv):
        html = urllib.request.urlopen(f"{srv}/dashboard", timeout=5).read().decode("utf-8", "ignore")
        assert "dashboard/static/dashboard.css" in html
        assert "dashboard/static/dashboard.js" in html
        assert "panel-mechanisms" in html  # 高级多面板结构
        assert "神经" in html or "Neural" in html
