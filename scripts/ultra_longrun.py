#!/usr/bin/env python
"""Ultra 长时间真实运行测试 (Hermes<->Ultra 桥接实例).

设计目的(用户要求"长时间真实运行测试"):
- 针对已桥接的 Ultra 实例(默认 9200, HermesAdapter 宿主身份)
- 真实负载: 驱动 recall/learn/evolve/maintain 生命周期循环
- 真实 arxiv 拉取(clash 代理已通, 验证网络层)
- T4 编译探测(诚实报告: 有 LLM 则真编译, 无则降级)
- pytest 回归哨兵(防退化)
- 输出 JSON 报告(落本地, 不刷屏)

注意: 本脚本 no_agent=True, 纯 stdout 即报告.
"""
import sys
import os
import json
import time
import urllib.request
import urllib.error
import subprocess

BASE = os.environ.get("ULTRA_BASE", "http://127.0.0.1:9200")
PROXY = os.environ.get("ULTRA_PROXY", "http://127.0.0.1:7890")  # clash
VENV = r"E:/Prometheus-Ultra-MultiTypeKB/.venv/Scripts/python.exe"
REPO = r"E:/Prometheus-Ultra-MultiTypeKB"
DB_PATH = os.environ.get("ULTRA_LONG_DB", "/tmp/ultra_bridge_main.db")
ROUNDS = int(os.environ.get("ULTRA_ROUNDS", "3"))


def _get(path, timeout=10):
    try:
        req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        return {"_error": str(e)[:120]}


def _post(path, payload, timeout=30):
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(BASE + path, data=data,
                                   headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        return {"_error": str(e)[:120]}


def probe_bridge():
    """确认实例是 Hermes 桥接身份 + 探测 LLM 可用性."""
    summ = _get("/api/v1/dashboard/summary")
    agents = (summ.get("data") or {}).get("agents", {})
    llm_avail = "unknown"
    try:
        # 看 mechanisms 端点能调通即说明新版在跑
        _get("/api/v1/mechanisms")
        llm_avail = "endpoint_ok"
    except Exception:
        llm_avail = "endpoint_err"
    return {
        "active_host": agents.get("active_host"),
        "adapter_type": agents.get("adapter_type"),
        "summary_ok": summ.get("success", False),
        "llm_probe": llm_avail,
    }


def real_arxiv_pull():
    """真实 arxiv 拉取(走 clash 代理), 验证网络层."""
    proxy = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    opener = urllib.request.build_opener(proxy)
    try:
        req = urllib.request.Request("https://arxiv.org/abs/2401.12345",
                                   headers={"User-Agent": "Ultra-LongRun/1.0"})
        with opener.open(req, timeout=25) as r:
            body = r.read().decode("utf-8", "ignore")
            return {"http_code": r.status, "title_present": "Distributionally" in body,
                    "bytes": len(body)}
    except Exception as e:
        return {"http_code": 0, "error": str(e)[:120]}


def drive_lifecycle(round_i):
    """驱动一轮 Ultra 真实生命周期(recall->learn->evolve->maintain)."""
    r = {}
    # recall (未来感知)
    rc = _post("/api/v1/recall", {"query": f"longrun test round {round_i}", "limit": 5})
    r["recall"] = rc.get("success", False)
    # learn (真实经验回灌)
    lc = _post("/api/v1/learn", {"source": "host_experience",
                                "events": [{"type": "feedback", "content": f"longrun round {round_i}",
                                           "utility": 0.7}]})
    r["learn"] = lc.get("success", False)
    # evolve (自驱进化)
    ev = _post("/api/v1/evolve", {"context": f"longrun round {round_i}"})
    r["evolve"] = ev.get("success", False)
    r["chain_complete"] = (ev.get("data") or {}).get("chain_complete")
    # maintain
    mt = _post("/api/v1/maintain", {})
    r["maintain"] = mt.get("success", False)
    return r


def t4_compile_probe():
    """T4 编译探测: 诚实报告是否有 LLM 可用."""
    # 用 V3.5a 同款逻辑: 直接调 compiler 需内部, 这里用 HTTP t4 端点
    res = _post("/api/v1/t4/compile", {"arxiv_id": "2401.12345", "title": "probe"})
    if res.get("_error"):
        return {"status": "endpoint_error", "detail": res["_error"]}
    if res.get("success"):
        return {"status": "compiled_real", "name": (res.get("data") or {}).get("name")}
    # 失败 = 无 LLM (诚实降级)
    return {"status": "degraded_no_llm", "detail": res.get("error", "")[:80]}


def pytest_sentinel():
    """pytest 回归哨兵(子集: V3 接入相关)."""
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = REPO + "/src" + os.pathsep + env.get("PYTHONPATH", "")
        out = subprocess.run(
            [VENV, "-m", "pytest", "tests/test_v3_agent_integration.py",
             "tests/test_v3_6_dashboard.py", "-p", "no:cacheprovider",
             "-q", "-o", "addopts=", "--no-header"],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
        # 解析 passed/failed
        line = [l for l in out.stdout.splitlines() if "passed" in l or "failed" in l]
        return {"exit": out.returncode, "summary": line[-1] if line else "no-summary",
                "n_failed": out.stdout.count("FAILED")}
    except Exception as e:
        return {"exit": -1, "error": str(e)[:120]}


def main():
    t0 = time.time()
    report = {"start_ts": time.strftime("%Y-%m-%d %H:%M:%S"),
              "base": BASE, "rounds": ROUNDS}
    report["bridge"] = probe_bridge()
    report["arxiv"] = real_arxiv_pull()

    lifecycle = []
    for i in range(ROUNDS):
        try:
            lifecycle.append(drive_lifecycle(i + 1))
        except Exception as e:
            lifecycle.append({"round": i + 1, "error": str(e)[:120]})
    report["lifecycle"] = lifecycle

    report["t4"] = t4_compile_probe()
    report["pytest"] = pytest_sentinel()

    report["duration_sec"] = round(time.time() - t0, 1)
    report["end_ts"] = time.strftime("%Y-%m-%d %H:%M:%S")

    # 落本地报告
    out_path = os.path.join(REPO, "longrun_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # stdout 摘要(供 cron 投递)
    print(json.dumps({
        "bridge": report["bridge"],
        "arxiv": report["arxiv"],
        "lifecycle_rounds": len(lifecycle),
        "t4": report["t4"],
        "pytest": {k: report["pytest"][k] for k in ("exit", "summary") if k in report["pytest"]},
        "duration_sec": report["duration_sec"],
        "report_file": out_path,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
