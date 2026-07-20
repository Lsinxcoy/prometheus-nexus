#!/usr/bin/env python
"""Nexus 最细粒度运行监控 (每30min) — 纯监控, 不驱动系统.

设计原则(对齐用户'颗粒度最细'要求):
- 数据来源: /api/v1/monitor/detail (Nexus 单机制级 + 系统指标 + 管道统计)
- 最细粒度: 单机制 invoke_count/effect/error_count/status/last_invoked
  + 沉默机制 + 路由接管 + 动态层 + 突触修剪 + 系统资源 + 管道 runs/failures
- 纯监控: 只读, 不 POST 生命周期(不人为制造流量, 看真实运行)
- 每30min 一轮, 后台常驻; 每轮发飞书

运行: python scripts/ultra_monitor_fine.py  (后台; 或 nohup)
依赖: 系统已跑 (api_server :9200)
"""
import sys, os, json, time, pathlib, datetime, urllib.request, urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.environ.get("NEXUS_API", "http://127.0.0.1:9200")
PROXY = os.environ.get("NEXUS_PROXY", "http://127.0.0.1:7890")
os.environ.setdefault("HTTPS_PROXY", PROXY)
os.environ.setdefault("HTTP_PROXY", PROXY)
INTERVAL = int(os.environ.get("NEXUS_MON_INTERVAL", "1800"))  # 30min


def call(path, timeout=30):
    try:
        req = urllib.request.Request(API + path)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"_error": str(e)[:200]}


TYPE_LABEL = {
    "knowledge": "📚 知识", "mechanism": "🧬 机制", "belief": "💡 信念",
    "reflection": "🪞 反思", "evolution": "🧠 进化", "prune": "🗑️ 修剪",
}


def _detail_line(ptype: str, d: dict) -> str:
    """从产出 detail 提取对人类有用的明细行."""
    if ptype == "knowledge":
        content = d.get("content", "")
        # learn 产出的 detail 含 title/url, remember 产出含 content
        title = d.get("title") or content
        tags = ",".join(d.get("tags", [])[:4]) if d.get("tags") else ""
        src = d.get("url", "")[:40] if d.get("url") else ""
        extra = f" [{tags}]" if tags else ""
        if src:
            extra += f" <- {src}"
        return f"{str(title)[:70]}{extra}"
    if ptype == "mechanism":
        name = d.get("name", "?")
        paper = d.get("paper", "")
        tgt = d.get("target_location", {})
        mod = tgt.get("module", "") if isinstance(tgt, dict) else ""
        accepted = d.get("accepted")
        flag = "✓emit" if accepted else "✗"
        return f"{name} {flag} {paper[-30:]} -> {mod}"
    if ptype == "belief":
        return (f"信念{d.get('beliefs_synthesized')} / 模式{d.get('patterns_found')} "
                f"/ 连接{d.get('connections_discovered')}")
    if ptype == "reflection":
        return f"评分={d.get('score')} 等级={d.get('grade')} 漂移={d.get('drift')}"
    if ptype == "evolution":
        return (f"{d.get('result')} Δfit={round(d.get('delta',0),4)} "
                f"({round(d.get('fitness_before',0),3)}→{round(d.get('fitness_after',0),3)}) "
                f"best={d.get('best_strategy')}")
    if ptype == "prune":
        return f"修剪{d.get('pruned')}节点 / 过期规则{d.get('expired_rules')} / 余{d.get('node_count')}"
    return ""


def build_report(detail: dict, prods: dict, issues: dict | None = None,
                 skills: dict | None = None) -> str:
    """产出视角报告: 这段时间系统产出了什么(而非机制健康)."""
    snap = detail.get("snapshot", {})
    pipes = detail.get("pipelines", {})
    sys_m = detail.get("system", {})
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    L = [f"🔬 Nexus 产出监控 {now}", ""]

    # —— 系统指标 ——
    L.append("【本周期产出】")
    by_type = prods.get("by_type", {})
    if not by_type:
        L.append("  (无新产出 — 系统静默运行)")
    else:
        for t, c in sorted(by_type.items(), key=lambda kv: -kv[1]):
            L.append(f"  {TYPE_LABEL.get(t, t)}: {c} 项")

    L.append(f"  产出总计: {prods.get('total', 0)} 项 (近 {prods.get('since_minutes')}min)")

    # —— 具体产出清单(每条) ——
    items = prods.get("items", [])
    if items:
        L.append("")
        L.append("【产出明细】")
        # 按类型分组, 每组最多 8 条
        for t in ("knowledge", "mechanism", "belief", "reflection", "evolution", "prune"):
            grp = [p for p in items if p["type"] == t]
            if not grp:
                continue
            L.append(f"  {TYPE_LABEL.get(t, t)}:")
            for p in grp[-8:]:
                ts = datetime.datetime.fromtimestamp(p["ts"]).strftime("%H:%M")
                d = p.get("detail", {})
                line = _detail_line(t, d)
                L.append(f"    [{ts}] {line}")

    # —— 管道运行(是否真的在跑) ——

    L.append("")
    L.append("【管道运行】")
    for pn, pv in sorted(pipes.items()):
        runs, fails = pv.get("runs", 0), pv.get("failures", 0)
        flag = "✅" if (fails == 0) else "⚠️"
        L.append(f"  {flag} {pn}: runs={runs} fail={fails}")

    # —— 系统资源(一行) ——
    L.append("")
    L.append("【系统】")
    if sys_m:
        L.append(f"  CPU {sys_m.get('cpu_percent')}% | 内存 {sys_m.get('memory_percent')}% | "
                 f"进程 {sys_m.get('process_memory_mb')}MB | 线程 {sys_m.get('thread_count')}")
    else:
        L.append("  (无系统指标)")
    L.append(f"  机制总数 {snap.get('mechanisms')} | 消费率 {round(snap.get('rate',0),3)} | "
             f"动态层 {snap.get('dynamic')}")

    # —— 运行问题(这段时间真实产生的 BUG/异常/关键WARNING) ——
    L.append("")
    L.append("【运行问题】")
    iss = issues.get("items", []) if issues else []
    by_level = (issues or {}).get("by_level", {})
    if not iss:
        L.append("  ✅ 无 ERROR/关键WARNING — 系统运行健康")
    else:
        if by_level:
            L.append(f"  汇总: error={by_level.get('error',0)} warning={by_level.get('warning',0)}")
        # 按 (level, source, msg) 聚合, 避免刷屏
        from collections import Counter
        agg = Counter()
        samples = {}
        for it in iss:
            key = (it.get("level"), it.get("source"), it.get("msg"))
            agg[key] += 1
            samples.setdefault(key, it)
        for (level, source, msg), cnt in sorted(agg.items(), key=lambda kv: -kv[1])[:10]:
            icon = "🔴" if level == "error" else "🟡"
            ts = datetime.datetime.fromtimestamp(samples[(level, source, msg)]["ts"]).strftime("%H:%M")
            rep = f"  {icon} [{ts}] {source}: {msg[:90]}"
            if cnt > 1:
                rep += f" (×{cnt})"
                L.append(rep)

    # —— 技能提炼(SEED 后见蒸馏 + Agentic Proposing 组合) ——
    L.append("")
    L.append("【技能提炼】")
    sk = skills or {}
    hp = sk.get("hindsight_playbooks", 0)
    hs = sk.get("hindsight_skills", 0)
    db = sk.get("distill_bonus", 0.0)
    if hp == 0 and hs == 0:
        L.append("  (本轮暂无新提炼 — 跑 learn/evolve/dream/reflect 后自动蒸馏)")
    else:
        L.append(f"  后见技能: {hs} 条 | 后见 playbook: {hp} 个 | 蒸馏奖励 Δ={round(db,4)}")
        for s in sk.get("samples", [])[:4]:
            L.append(f"  🧬 {s.get('type','')}: {s.get('body','')[:48]}")

    return "\n".join(L)


def send_feishu(text: str) -> bool:
    secret_path = pathlib.Path(REPO) / "feishu_secret.json"
    if not secret_path.exists():
        print("[WARN] feishu_secret.json 不存在, 跳过飞书发送")
        print(text)
        return False
    try:
        cfg = json.loads(secret_path.read_text(encoding="utf-8"))
        app_id, app_secret, chat_id = cfg["app_id"], cfg["app_secret"], cfg["chat_id"]
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
    # send
    try:
        msg_req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            data=json.dumps({
                "receive_id": chat_id, "msg_type": "text",
                "content": json.dumps({"text": text}),
            }).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(msg_req, timeout=15) as r:
            res = json.loads(r.read().decode())
        if res.get("code") == 0:
            print(f"[OK] 飞书发送成功 {datetime.datetime.now()}")
            return True
        print(f"[ERR] 发送失败: {res}")
        return False
    except Exception as e:
        print(f"[ERR] 发送异常: {e}")
        return False


def tick():
    """一轮监控: 拉产出视角数据 + 发飞书."""
    detail = call("/api/v1/monitor/detail")
    if "_error" in detail:
        msg = f"⚠️ Nexus 监控取数失败: {detail['_error']}\nAPI={API}\n请检查系统是否在跑"
        print(msg)
        send_feishu(msg)
        return False
    prods = call("/api/v1/productions?since_minutes=30")
    if "_error" in prods:
        prods = {"total": 0, "by_type": {}, "items": [], "since_minutes": 30}
    issues = call("/api/v1/issues?since_minutes=30")
    if "_error" in issues:
        issues = {"total": 0, "by_level": {}, "items": [], "since_minutes": 30}
    skills = call("/api/v1/skills")
    if "_error" in skills:
        skills = {"hindsight_playbooks": 0, "hindsight_skills": 0,
                  "total_playbooks": 0, "total_skills": 0, "distill_bonus": 0.0, "samples": []}
    text = build_report(detail, prods, issues, skills)
    send_feishu(text)
    # 落盘备查
    try:
        out = pathlib.Path(REPO) / "monitor_fine_latest.json"
        out.write_text(json.dumps({"detail": detail, "productions": prods,
                                    "issues": issues, "skills": skills},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return True


if __name__ == "__main__":
    print(f"[启动] Nexus 产出监控 每 {INTERVAL}s (API={API})")
    # 首轮立即跑
    tick()
    while True:
        time.sleep(INTERVAL)
        try:
            tick()
        except Exception as e:
            print(f"[ERR] tick 异常: {e}")
