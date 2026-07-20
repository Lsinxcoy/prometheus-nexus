#!/usr/bin/env python
"""Ultra 9200 守护: 每60s探活, 挂了自动拉起 (后台常驻).

用法:
  python ultra_keepalive.py           # 前台常驻 (建议用任务计划/WSL background 跑)
  python ultra_keepalive.py --once    # 只探一次, 挂了就拉起然后退出 (适合 cron 风格)
"""
import sys, os, subprocess, time, urllib.request, json

REPO = "E:/Prometheus-Ultra-MultiTypeKB"
PYTHON = os.path.join(REPO, ".venv", "Scripts", "python.exe")
DB = os.path.join(REPO, "src", "prometheus_nexus.db")
HOST, PORT = "127.0.0.1", 9200
HEALTH = f"http://{HOST}:{PORT}/api/v1/health"


def is_up():
    try:
        with urllib.request.urlopen(HEALTH, timeout=5) as r:
            return json.loads(r.read().decode()).get("status") == "healthy"
    except Exception:
        return False


def launch():
    subprocess.Popen(
        [PYTHON, "-m", "prometheus_nexus.services.api_server",
         "--host", HOST, "--port", str(PORT), "--db-path", DB],
        cwd=REPO, creationflags=0x00000008,  # DETACHED_PROCESS
    )
    print(f"[keepalive] launched 9200 (db={DB})")


if __name__ == "__main__":
    if "--once" in sys.argv:
        if not is_up():
            print("[keepalive] down -> launching")
            launch()
        else:
            print("[keepalive] up, no action")
        sys.exit(0)
    # 常驻模式
    print("[keepalive] daemon start, polling every 60s")
    while True:
        if not is_up():
            print("[keepalive] 9200 DOWN, relaunching...")
            launch()
        time.sleep(60)
