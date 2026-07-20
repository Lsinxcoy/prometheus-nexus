#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Nexus 长时间运行监控 (事件驱动 + 区间 digest).

三类报告:
  A. LEARN 触发捕获: 一次 learn 触发学到的全部知识 + 同步触发链(reflect/evolve/dream/belief/prune)
     全部产物, 按 event_id 精确归链, learn 链采集完后立即发送(不截断).
  B. 区间产物 Digest: 两次轮询间其它管道产物 + 系统指标, 默认 30min 一条(区间非空才发).
  C. 运行问题: 系统运行期间真实产生的 BUG/异常/关键WARNING, 新问题立即告警 + digest 汇总.

数据来源(真实端点):
  GET /api/v1/productions?since_minutes=N  -> items:[{id,ts,type,summary,detail,event_id,parent}]
  GET /api/v1/monitor/detail               -> {snapshot,pipelines,system}
  GET /api/v1/issues?since_minutes=N        -> items:[{ts,level,source,msg}]
  GET /api/v1/skills                        -> {hindsight_playbooks,hindsight_skills,distill_bonus,samples}

设计:
  - 轮询 + 状态持久化(monitor_state.json): 重启续传, 不重复发.
  - 增量去重: 靠 production id 去重.
  - 可管理: 启动 HTTP 健康检查(9270) + /shutdown(GET 即停). 由 Hermes 后台进程托管, 可见可 kill.
  - 9200 不可达: 仅发一次告警后静默, 恢复后继续.
"""
import sys, os, json, time, argparse, datetime, threading, urllib.request, urllib.error, http.server

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.environ.get("NEXUS_API", "http://127.0.0.1:9200")
PROXY = os.environ.get("NEXUS_PROXY", "http://127.0.0.1:7890")
os.environ.setdefault("HTTPS_PROXY", PROXY)
os.environ.setdefault("HTTP_PROXY", PROXY)

TYPE_LABEL = {
    "knowledge": "📚 知识", "mechanism": "🧬 机制", "belief": "💡 信念",
    "reflection": "🪞 反思", "evolution": "🧠 进化", "prune": "🗑️ 修剪",
}
CHAIN_TYPES = ("reflection", "evolution", "belief", "prune", "mechanism")
CHAIN_WINDOW = 90          # learn 链采集窗口(秒): 该 eid 最新产物超过此年龄则发送
DIGEST_SEC = 1800          # 区间报告周期
POLL_SEC = 20              # 轮询间隔
HEALTH_PORT = 9270
MAX_CHARS = 3500           # 单条飞书分块阈值


def call(path, timeout=30):
    try:
        req = urllib.request.Request(API + path)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"_error": str(e)[:200]}


def _detail_line(ptype, d):
    d = d or {}
    if ptype == "knowledge":
        content = d.get("content", "")
        title = d.get("title") or content
        tags = ",".join(d.get("tags", [])[:6]) if d.get("tags") else ""
        src = d.get("url", "")[:50] if d.get("url") else ""
        extra = f" [{tags}]" if tags else ""
        if src:
            extra += f" <- {src}"
        body = str(title)[:400]
        return f"{body}{extra}"
    if ptype == "mechanism":
        name = d.get("name", "?")
        paper = d.get("paper", "")
        tgt = d.get("target_location", {})
        mod = tgt.get("module", "") if isinstance(tgt, dict) else ""
        accepted = d.get("accepted")
        flag = "✓emit" if accepted else "✗"
        return f"{name} {flag} {str(paper)[-30:]} -> {mod}"
    if ptype == "belief":
        return (f"信念{d.get('beliefs_synthesized')} / 模式{d.get('patterns_found')} "
                f"/ 连接{d.get('connections_discovered')}")
    if ptype == "reflection":
        return f"评分={d.get('score')} 等级={d.get('grade')} 漂移={d.get('drift')}"
    if ptype == "evolution":
        return (f"{d.get('result')} Δfit={round(d.get('delta', 0), 4)} "
                f"({round(d.get('fitness_before', 0), 3)}→{round(d.get('fitness_after', 0), 3)}) "
                f"best={d.get('best_strategy')}")
    if ptype == "prune":
        return f"修剪{d.get('pruned')}节点 / 过期规则{d.get('expired_rules')} / 余{d.get('node_count')}"
    return ""


# ---------------- 飞书发送 ----------------
def send_feishu(text, secret_path, chat_override=None):
    if not os.path.exists(secret_path):
        print(f"[WARN] 凭据缺失 {secret_path}, 跳过发送:\n{text}")
        return False
    try:
        cfg = json.loads(open(secret_path, encoding="utf-8").read())
        app_id, app_secret = cfg["app_id"], cfg["app_secret"]
        chat_id = chat_override or cfg.get("chat_id")
        if not chat_id:
            print("[WARN] 无 chat_id, 跳过")
            return False
    except Exception as e:
        print(f"[ERR] 读凭据失败: {e}")
        return False
    # token
    try:
        tok_req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(tok_req, timeout=15) as r:
            tok = json.loads(r.read().decode())
        if tok.get("code") != 0:
            print(f"[ERR] token 失败: {tok}")
            return False
        token = tok["tenant_access_token"]
    except Exception as e:
        print(f"[ERR] token 异常: {e}")
        return False
    # 分块发送
    chunks = _split(text, MAX_CHARS)
    ok = True
    for i, ch in enumerate(chunks):
        payload = json.dumps({"receive_id": chat_id, "msg_type": "text",
                              "content": json.dumps({"text": ch})}).encode()
        try:
            msg_req = urllib.request.Request(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                data=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(msg_req, timeout=15) as r:
                res = json.loads(r.read().decode())
            if res.get("code") != 0:
                print(f"[ERR] 发送失败: {res}")
                ok = False
        except Exception as e:
            print(f"[ERR] 发送异常: {e}")
            ok = False
    if ok:
        print(f"[OK] 飞书发送成功 {datetime.datetime.now()} ({len(chunks)}块)")
    return ok


def _split(text, n):
    if len(text) <= n:
        return [text]
    lines = text.split("\n")
    out, cur = [], ""
    for ln in lines:
        if len(cur) + len(ln) + 1 > n and cur:
            out.append(cur)
            cur = ln
        else:
            cur = cur + "\n" + ln if cur else ln
    if cur:
        out.append(cur)
    return out


# ---------------- 状态 ----------------
def load_state(path):
    try:
        return json.loads(open(path, encoding="utf-8").read())
    except Exception:
        return {"seen_ids": [], "last_digest_ts": 0.0, "last_issue_key": {},
                "down_since": None, "pending": {}}


def save_state(path, st):
    try:
        tmp = path + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(st, ensure_ascii=False))
        os.replace(tmp, path)
    except Exception as e:
        print(f"[ERR] 存状态失败: {e}")


# ---------------- 报告渲染 ----------------
def _fmt_ts(t):
    return datetime.datetime.fromtimestamp(t).strftime("%H:%M:%S")


def render_learn_event(eid, items):
    """items: 该 event_id 下的全部 production(含 learn 知识 + 链产物)."""
    items = sorted(items, key=lambda x: x.get("ts", 0))
    know = [i for i in items if i["type"] == "knowledge"]
    chain = [i for i in items if i["type"] in CHAIN_TYPES]
    L = [f"🔔 [LEARN 触发] {_fmt_ts(items[0]['ts'])}  event_id={eid}"]
    L.append("── 本次学习到的知识 ──")
    if know:
        for k in know:
            L.append(f"  📚 K-{k.get('id','')[:8]}  {_detail_line('knowledge', k.get('detail', {}))}")
    else:
        L.append("  (无新知识节点)")
    L.append("── 触发链产物 ──")
    if chain:
        for c in chain:
            L.append(f"  {TYPE_LABEL.get(c['type'], c['type'])} [{_fmt_ts(c['ts'])}] {_detail_line(c['type'], c.get('detail', {}))}")
    else:
        L.append("  (链未产生其它产物)")
    # 链健康
    present = {i["type"] for i in items}
    health = []
    for t in ("knowledge", "reflection", "evolution", "belief", "prune"):
        health.append(f"{TYPE_LABEL.get(t, t)[0]}✓" if t in present else f"{TYPE_LABEL.get(t, t)[0]}—")
    L.append(f"── 链健康 ──  {' '.join(health)}")
    return "\n".join(L)


def render_digest(interval_items, detail, issues):
    L = [f"📊 [区间产物] {_fmt_ts(time.time() - DIGEST_SEC)} – {_fmt_ts(time.time())}"]
    by_type = {}
    for it in interval_items:
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1
    if not by_type:
        L.append("  (本区间无新产物)")
    else:
        for t, c in sorted(by_type.items(), key=lambda kv: -kv[1]):
            L.append(f"  {TYPE_LABEL.get(t, t)}: {c}")
        # 每类取最新 2 条样例
        for t in ("knowledge", "mechanism", "reflection", "evolution", "belief", "prune"):
            grp = [p for p in interval_items if p["type"] == t]
            if not grp:
                continue
            L.append(f"  【{TYPE_LABEL.get(t, t)}样例】")
            for p in sorted(grp, key=lambda x: x.get("ts", 0))[-2:]:
                L.append(f"    [{_fmt_ts(p['ts'])}] {_detail_line(t, p.get('detail', {}))}")
    # 系统
    snap = (detail or {}).get("snapshot", {})
    sys_m = (detail or {}).get("system", {})
    pipes = (detail or {}).get("pipelines", {})
    L.append("── 系统 ──")
    if sys_m:
        L.append(f"  CPU {sys_m.get('cpu_percent')}% | 内存 {sys_m.get('memory_percent')}% | "
                 f"进程 {sys_m.get('process_memory_mb')}MB | 线程 {sys_m.get('thread_count')}")
    L.append(f"  机制总数 {snap.get('mechanisms')} | 消费率 {round(snap.get('rate', 0), 3)} | 动态层 {snap.get('dynamic')}")
    L.append("── 管道运行 ──")
    for pn, pv in sorted(pipes.items()):
        runs, fails = pv.get("runs", 0), pv.get("failures", 0)
        flag = "✅" if fails == 0 else "⚠️"
        L.append(f"  {flag} {pn}: runs={runs} fail={fails}")
    # 问题汇总
    iss = (issues or {}).get("items", [])
    bl = (issues or {}).get("by_level", {})
    L.append("── 运行问题 ──")
    if not iss:
        L.append("  ✅ 无 ERROR/关键WARNING")
    else:
        L.append(f"  汇总: error={bl.get('error', 0)} warning={bl.get('warning', 0)}")
    return "\n".join(L)


def render_issue(it):
    icon = "🔴" if it.get("level") == "error" else "🟡"
    return f"{icon} {it.get('level')} {it.get('source')}: {it.get('msg')[:120]}"


# ---------------- 主循环 ----------------
class Monitor:
    def __init__(self, secret_path, chat=None, dry=False):
        self.secret = secret_path
        self.chat = chat
        self.dry = dry
        self.state = load_state(os.path.join(REPO, "monitor_state.json"))
        self.state.setdefault("seen_ids", [])
        self.state.setdefault("last_digest_ts", 0.0)
        self.state.setdefault("last_issue_key", {})
        self.state.setdefault("down_since", None)
        self.state.setdefault("pending", {})
        self._stop = threading.Event()
        self.pending_eids = {}  # eid -> 最新 ts(链采集窗口跟踪)
        self._seen = set(self.state["seen_ids"][-2000:])

    def _emit(self, text):
        print(f"[SEND {datetime.datetime.now():%H:%M:%S}]\n{text}", flush=True)
        if self.dry:
            return
        send_feishu(text, self.secret, self.chat)

    def tick(self):
        detail = call("/api/v1/monitor/detail")
        if "_error" in detail:
            if self.state.get("down_since") is None:
                self.state["down_since"] = time.time()
                self._emit(f"⚠️ Nexus 监控取数失败: {detail['_error']}\nAPI={API}\n请检查系统是否在跑")
            return
        else:
            if self.state.get("down_since") is not None:
                print("[INFO] 9200 恢复")
                self.state["down_since"] = None

        # 1. productions (增量: 从上次最后 ts 到现在, 不漏任何事件)
        last_ts = self.state.get("last_prod_ts", 0)
        since = max((time.time() - last_ts) / 60 + 1, 1)
        prods = call(f"/api/v1/productions?since_minutes={since}")
        new_items = []
        if "items" in prods:
            mx = last_ts
            for it in prods["items"]:
                iid = it.get("id")
                if iid in self._seen:
                    continue
                self._seen.add(iid)
                self.state["seen_ids"].append(iid)
                new_items.append(it)
                mx = max(mx, it.get("ts", 0))
            self.state["last_prod_ts"] = mx
        now = time.time()
        # 分类
        for it in new_items:
            eid = it.get("event_id")
            if eid:
                self.pending_eids[eid] = max(self.pending_eids.get(eid, 0), it.get("ts", now))
            else:
                self.state.setdefault("_interval", []).append(it)

        # 2. learn 事件: 链采集窗口到期, 重拉完整链(含时间窗口内异步链产物)发送
        for eid, latest in list(self.pending_eids.items()):
            if now - latest >= CHAIN_WINDOW:
                chain = self._fetch_chain(eid, latest)
                self._emit(render_learn_event(eid, chain))
                del self.pending_eids[eid]

        # 3. issues (事件驱动)
        issues = call(f"/api/v1/issues?since_minutes={max(POLL_SEC/60*2, 1)}")
        if "items" in issues:
            new_iss = []
            for it in issues["items"]:
                key = (it.get("level"), it.get("source"), it.get("msg"))
                last = self.state["last_issue_key"].get(str(key), 0)
                if now - last > 300:  # 同问题 5min 内只报一次
                    self.state["last_issue_key"][str(key)] = now
                    new_iss.append(it)
            for it in new_iss:
                self._emit(render_issue(it))

        # 4. digest
        interval = self.state.get("_interval", [])
        if now - self.state["last_digest_ts"] >= DIGEST_SEC:
            if interval or True:  # 即使空也发(便于长测确认存活)
                self._emit(render_digest(interval, detail, issues if "items" in issues else None))
            self.state["_interval"] = []
            self.state["last_digest_ts"] = now

        # 落盘
        self.state["seen_ids"] = self.state["seen_ids"][-3000:]
        save_state(os.path.join(REPO, "monitor_state.json"), self.state)

    def _fetch_chain(self, eid, learn_ts):
        """重拉 learn 事件完整链: 该 eid 全部 + 时间窗口内异步触发的链产物(eid=None)."""
        prods = call(f"/api/v1/productions?since_minutes={(time.time() - learn_ts) / 60 + 1}")
        items = prods.get("items", [])
        return [i for i in items if i.get("event_id") == eid
                or (i.get("event_id") is None and i.get("type") in CHAIN_TYPES
                    and learn_ts <= i.get("ts", 0) <= learn_ts + CHAIN_WINDOW + 30)]

    def run(self):
        print(f"[启动] Nexus 监控 每 {POLL_SEC}s | digest {DIGEST_SEC}s | chain_window {CHAIN_WINDOW}s | API={API}")
        self.tick()  # 首轮
        while not self._stop.is_set():
            time.sleep(POLL_SEC)
            try:
                self.tick()
            except Exception as e:
                print(f"[ERR] tick 异常: {e}")

    def stop(self):
        self._stop.set()


# ---------------- 健康检查/停止 HTTP ----------------
def make_handler(monitor):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/shutdown":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"stopping")
                monitor.stop()
            elif self.path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(404)
                self.end_headers()
        def log_message(self, *a):
            pass
    return H


def main():
    global API, DIGEST_SEC, POLL_SEC, CHAIN_WINDOW
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=API)
    ap.add_argument("--secret", default=os.path.join(REPO, "feishu_secret.json"))
    ap.add_argument("--chat", default=None, help="飞书 chat_id 覆盖")
    ap.add_argument("--digest-sec", type=int, default=DIGEST_SEC)
    ap.add_argument("--poll-sec", type=int, default=POLL_SEC)
    ap.add_argument("--chain-window", type=int, default=CHAIN_WINDOW)
    ap.add_argument("--health-port", type=int, default=HEALTH_PORT)
    ap.add_argument("--dry", action="store_true", help="只打印不发飞书")
    args = ap.parse_args()

    API = args.api
    DIGEST_SEC, POLL_SEC, CHAIN_WINDOW = args.digest_sec, args.poll_sec, args.chain_window

    m = Monitor(args.secret, args.chat, args.dry)
    t = threading.Thread(target=lambda: http.server.HTTPServer(("127.0.0.1", args.health_port),
                                                                make_handler(m)).serve_forever(), daemon=True)
    t.start()
    print(f"[健康检查] http://127.0.0.1:{args.health_port}/health  /shutdown")
    try:
        m.run()
    except KeyboardInterrupt:
        m.stop()


if __name__ == "__main__":
    main()
