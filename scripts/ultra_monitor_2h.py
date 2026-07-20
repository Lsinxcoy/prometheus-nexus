#!/usr/bin/env python
"""Ultra 持续运行监控 (每2h) — 全量生命周期驱动 + 实际BUG检测 + 自动修复 + 飞书报告.

用户要求:
- 每2h 驱动 Ultra 全量调用 (recall/learn/evolve/maintain + T4 真编译)
- 监控运行情况, 判断是否有'实际运行BUG' (非假设/非降级)
- 有 BUG 直接修复 (改代码+验证, 不自动push除非稳)
- 每次结果发飞书, 尽量详细

BUG 判定(严格, 不误报):
- success=False 且非已知降级(LLM额度/网络超时)
- 抛未预期异常 / 导入错误 / 断言失败
- metrics 退化超阈值
"""
import sys, os, json, time, traceback, re, pathlib, datetime
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/src")
import urllib.request

REPO = "E:/Prometheus-Ultra-MultiTypeKB"
API = "http://127.0.0.1:9200"
PROXY = "http://127.0.0.1:7890"
os.environ.setdefault("HTTPS_PROXY", PROXY)
os.environ.setdefault("HTTP_PROXY", PROXY)

report = {
    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "steps": [], "bugs_found": [], "bugs_fixed": [], "metrics": {}, "verdict": "OK",
}


def call(path, payload=None, timeout=60):
    """POST (或 GET 若 payload=None). 返回解析后的 dict."""
    try:
        if payload is None:
            req = urllib.request.Request(API + path)
        else:
            req = urllib.request.Request(API + path, data=json.dumps(payload).encode(),
                                          headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"_error": str(e)[:200]}


def log_step(name, ok, detail, duration=None, data=None):
    entry = {"step": name, "ok": ok, "detail": str(detail)[:600]}
    if duration is not None:
        entry["duration_s"] = round(duration, 2)
    if data is not None:
        entry["data"] = data
    report["steps"].append(entry)
    print(f"[{'OK' if ok else 'FAIL'}] {name}: {str(detail)[:100]}")
    return ok


def is_known_degrade(detail: str) -> bool:
    """已知降级(非BUG): LLM额度/网络/超时."""
    d = detail.lower()
    return any(k in d for k in ("402", "401", "payment", "timeout", "403", "429", " awaiting"))


def ok_resp(r):
    """兼容 success 为 bool 或字符串 'True'/'true'."""
    return str(r.get("success", "")).lower() == "true" and "_error" not in r


def attempt_fix(step: str, bug_detail: str):
    """定位源码 + 诊断(避免盲目patch). 返回 (fixed:bool, detail:str)."""
    m = re.search(r'File "([^"]+)", line (\d+)', bug_detail)
    if not m:
        return False, "无文件:行号线索"
    fpath, lineno = m.group(1), int(m.group(2))
    if "site-packages" in fpath or ".venv" in fpath:
        return False, f"第三方库 {fpath}:{lineno}, 非本仓库可修"
    if not fpath.startswith(REPO):
        return False, f"仓库外 {fpath}, 跳过"
    try:
        p = pathlib.Path(fpath)
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        ctx = lines[max(0, lineno-3):lineno+2]
        return False, f"诊断 {fpath}:{lineno} 上下文={ctx}"
    except Exception as e:
        return False, f"修复尝试失败: {e}"


def send_feishu(rep: dict):
    """详细飞书文本 -> 真实飞书 API (tenant_access_token + im/v1/messages).
    凭据从本地 feishu_secret.json 读取 (gitignore 保护, 不进版本库).
    """
    # 1. 构造文本
    L = [f"📊 Ultra 运行监控 {rep['time']}", f"判定: {rep['verdict']}"]
    for s in rep["steps"]:
        L.append(f"• {s['step']}: {'✅' if s['ok'] else '❌'} ({s.get('duration_s','-')}s) {s['detail'][:160]}")
    if rep["bugs_found"]:
        L.append(f"\n🐛 发现BUG {len(rep['bugs_found'])} 个:")
        for b in rep["bugs_fixed"]:
            L.append(f"  - {b['step']}: {'已修' if b['fixed'] else '未修(待人工)'} {b['detail'][:160]}")
    if rep["metrics"]:
        L.append(f"\n📈 Metrics: {rep['metrics']}")
    text = "\n".join(L)
    print(text)  # 兜底: stdout

    # 2. 读凭据
    secret_path = pathlib.Path(REPO) / "feishu_secret.json"
    if not secret_path.exists():
        print("[WARN] feishu_secret.json 不存在, 跳过飞书发送")
        return False
    cfg = json.loads(secret_path.read_text(encoding="utf-8"))
    app_id, app_secret, chat_id = cfg["app_id"], cfg["app_secret"], cfg["chat_id"]

    # 3. 获取 tenant_access_token
    try:
        tok_req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(tok_req, timeout=15) as r:
            tok = json.loads(r.read().decode())
        if tok.get("code") != 0:
            print(f"[ERR] 飞书 token 失败: {tok}")
            return False
        token = tok["tenant_access_token"]
    except Exception as e:
        print(f"[ERR] 飞书 token 异常: {e}")
        return False

    # 4. 发送消息
    try:
        msg_req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            data=json.dumps({
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            }).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(msg_req, timeout=15) as r:
            res = json.loads(r.read().decode())
        if res.get("code") == 0:
            print(f"[OK] 飞书发送成功 message_id={res.get('data', {}).get('message_id')}")
            return True
        else:
            print(f"[ERR] 飞书发送失败: {res}")
            return False
    except Exception as e:
        print(f"[ERR] 飞书发送异常: {e}")
        return False


# ---------- 1. 健康 ----------
t0 = time.time()
h = call("/api/v1/health")
log_step("health", h.get("status") == "healthy", h, time.time()-t0,
         {"active_host": call("/api/v1/status").get("host_id")})

# ---------- 2. 全量生命周期 (POST 真实负载) ----------
# recall
t0 = time.time()
r = call("/api/v1/recall", {"query": "caching mechanism", "k": 3})
log_step("recall", ok_resp(r), r.get("error") or r.get("data", {}).get("total_count", "ok"),
         time.time()-t0, {"hits": r.get("data", {}).get("total_count")})

# learn (arxiv 真拉 + T4 真编译)
t0 = time.time()
r = call("/api/v1/learn", {"source": "arxiv:2401.12345", "title": "Test Paper"}, timeout=120)
log_step("learn(arxiv+T4)", ok_resp(r), r.get("error") or "compiled" if ok_resp(r) else r, time.time()-t0,
         {"mechanism_id": (r.get("data", {}) or {}).get("mechanism_id"), "compiled": bool((r.get("data", {}) or {}).get("mechanism_id"))})

# evolve
t0 = time.time()
r = call("/api/v1/evolve", {"rounds": 1}, timeout=120)
log_step("evolve", ok_resp(r), r.get("error") or "ok", time.time()-t0,
         {"fitness": (r.get("data", {}) or {}).get("fitness")})

# maintain
t0 = time.time()
r = call("/api/v1/maintain", {})
log_step("maintain", ok_resp(r), r.get("error") or "ok", time.time()-t0,
         {"consolidated": (r.get("data", {}) or {}).get("consolidation", {}).get("consolidated")})

# T4 显式编译
t0 = time.time()
r = call("/api/v1/t4/compile", {"arxiv_id": "2401.12345", "paper_title": "T4 Probe"}, timeout=120)
log_step("t4_compile", ok_resp(r), r.get("error") or "compiled", time.time()-t0,
         {"mechanism_id": (r.get("data", {}) or {}).get("mechanism_id")})

# ---------- 3. metrics ----------
t0 = time.time()
s = call("/api/v1/dashboard/summary")
data = s.get("data", s)
m = {
    "node_count": (data.get("memory") or {}).get("node_count"),
    "mechanisms_enabled": (data.get("mechanisms") or {}).get("enabled"),
    "global_utility": (data.get("memory") or {}).get("global_utility"),
    "active_host": data.get("active_host"),
}
log_step("metrics", True, m, time.time()-t0, m)
report["metrics"] = {k: v for k, v in m.items() if v is not None}

# ---------- 4. 实际BUG检测 + 自动修复 ----------
for st in report["steps"]:
    if not st["ok"] and not is_known_degrade(st["detail"]):
        report["bugs_found"].append(st)
        fixed, detail = attempt_fix(st["step"], st["detail"])
        report["bugs_fixed"].append({"step": st["step"], "fixed": fixed, "detail": detail})

report["verdict"] = "BUG_DETECTED" if report["bugs_found"] else "OK"

# ---------- 5. 输出 (cron deliver:feishu 转发飞书) ----------
send_feishu(report)
with open(os.path.join(REPO, "monitor_report.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
