"""Prometheus Nexus API Server — FastAPI wrapper around Omega.

Exposes all 7 pipelines as HTTP endpoints:
  POST /api/v1/remember
  POST /api/v1/recall
  POST /api/v1/evolve
  POST /api/v1/learn
  POST /api/v1/reflect
  POST /api/v1/dream
  POST /api/v1/maintain
  GET  /api/v1/status
  GET  /api/v1/health
  POST /api/v1/branch/create
  POST /api/v1/branch/merge
  GET  /api/v1/branch/list
"""

from __future__ import annotations

# Suppress coroutine RuntimeWarning pollution per Pitfall #23
import warnings
warnings.filterwarnings("ignore", message=".*coroutine.*was never awaited.*")

import sys

# Stderr interposition: clean coroutine pollution from async libs
class _CleanStderr:
    """Filter coroutine repr pollution from stderr (bypassed by uvicorn but catches startup)."""
    _orig_stderr = sys.stderr
    _coroutine_prefix = "<coroutine object "
    
    def write(self, text):
        if self._coroutine_prefix not in text:
            self._orig_stderr.write(text)
    
    def flush(self):
        self._orig_stderr.flush()

# Apply stderr wrapper for startup pollution
if not isinstance(sys.stderr, _CleanStderr):
    sys.stderr = _CleanStderr()

import json
import logging
import threading
import time
from typing import Any, Dict, Optional

# Optional: rubas_evaluator was removed, use rubric instead
try:
    from prometheus_nexus.safety.rubric import RubricScorer
    _HAS_RUBRIC = True
except ImportError:
    _HAS_RUBRIC = False

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Request/Response Models ──────────────────────────────────────────


class RememberRequest(BaseModel):
    content: str = ""
    utility: float = 0.5
    tags: list[str] = []


class RecallRequest(BaseModel):
    query: str = ""
    limit: int = 10


class EvolveRequest(BaseModel):
    context: str = ""
    branch: str = "main"
    confidence: float = 0.5


class LearnRequest(BaseModel):
    source: str = "web"
    query: str = ""
    max_results: int = 5


class ReflectRequest(BaseModel):
    context: str = ""


class DreamRequest(BaseModel):
    branch: str = "main"


class BranchCreateRequest(BaseModel):
    name: str
    parent: str = "main"


class BranchMergeRequest(BaseModel):
    source: str
    target: str = "main"


class ReportUsageRequest(BaseModel):
    node_id: str
    was_useful: bool = True
    query: str = ""
    context: str = ""


class UpdateNodeRequest(BaseModel):
    content: str = ""
    utility: float = -1.0  # -1 means keep current


class NodeSearchRequest(BaseModel):
    query: str = ""
    tags: list[str] = []
    min_utility: float = 0.0
    limit: int = 20


class PipelineResponse(BaseModel):
    success: bool
    pipeline: str
    data: Dict[str, Any] = {}
    error: Optional[str] = None
    duration_ms: float = 0.0


# ── Server Class ─────────────────────────────────────────────────────


class UltraAPIServer:
    """FastAPI server wrapping an Omega instance.

    Usage:
        server = UltraAPIServer(host="0.0.0.0", port=9200)
        server.start()
        # Omega is accessible via server.omega
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9200, db_path: Optional[str] = None):
        self.host = host
        self.port = port
        self.db_path = db_path
        self.app = FastAPI(title="Prometheus Nexus API", version="1.0.0")
        # 全局异常捕获: 任何端点未处理异常 -> 记运行问题(供监控报告"运行问题"块)
        from fastapi import Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse

        @self.app.exception_handler(Exception)
        async def _catch_all(req: Request, exc: Exception):
            src = f"api:{req.method} {req.url.path}"
            msg = f"{type(exc).__name__}: {str(exc)[:120]}"
            try:
                if self.omega and hasattr(self.omega, "record_issue"):
                    self.omega.record_issue("error", src, msg)
            except Exception:
                pass
            return JSONResponse(status_code=500, content={"error": msg, "source": src})

        @self.app.exception_handler(RequestValidationError)
        async def _catch_validation(req: Request, exc: RequestValidationError):
            # 输入校验错误不进运行问题(属调用方问题, 非系统 BUG)
            return JSONResponse(status_code=422, content={"detail": "validation error", "errors": str(exc)[:200]})

        # CORS for dashboard
        from fastapi.middleware.cors import CORSMiddleware

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self.omega = None
        self._server_thread: Optional[threading.Thread] = None
        self._setup_routes()

    def _setup_routes(self):
        app = self.app

        @app.get("/api/v1/owner-harm/violations")
        def owner_harm_violations(limit: int = 20):
            """返回最近 boundary violation (跨重启持久化). 供监控定性良性/恶性."""
            try:
                oh = getattr(self.omega, "owner_harm", None)
                if oh is None:
                    return {"violations": [], "count": 0, "source": "memory_only"}
                recent = oh.get_boundary_violations(limit=limit)
                # 内存最新 + 持久化文件(更全面) -> 合并去重(按 ts+node_id+requester)
                import os, json
                merged = list(recent)
                try:
                    if os.path.exists(oh._viol_log_path):
                        buf = json.load(open(oh._viol_log_path, encoding="utf-8"))
                        seen = {(v.get("ts"), v.get("node_id"), v.get("requester")) for v in recent}
                        for v in buf:
                            k = (v.get("ts"), v.get("node_id"), v.get("requester"))
                            if k not in seen:
                                merged.append(v)
                                seen.add(k)
                except Exception:
                    pass
                merged.sort(key=lambda v: v.get("ts", 0), reverse=True)
                return {"violations": merged[:limit], "count": len(merged), "source": "persisted"}
            except Exception as e:
                return {"violations": [], "count": 0, "error": str(e)[:160]}

        @app.get("/api/v1/health")
        def health():
            # 真实健康探测 —— 不再硬编码 healthy。
            # 旧实现恒定返回 {"status": "healthy"}, 导致 Omega 引擎未初始化或
            # 已失效时, 看门狗(ultra_keepalive)与监控(ultra_monitor_2h)仍报绿,
            # 真实薄弱被隐藏(监控盲区)。
            # 设计: status 仅表达"存活"(引擎已初始化且能响应), 避免看门狗把
            # "降级/临界"误判为"死亡"而误重启; 真实子系统健康由 engine_health
            # 暴露(healthy/degraded/critical/empty/unknown)。
            if self.omega is None:
                return {
                    "status": "unhealthy",
                    "service": "prometheus-nexus",
                    "engine_health": "unavailable",
                    "detail": "Omega engine not initialized",
                }
            try:
                s = self.omega.status()
                return {
                    "status": "healthy",
                    "service": "prometheus-nexus",
                    "engine_health": s.health,
                    "detail": "engine online",
                }
            except Exception as e:
                return {
                    "status": "unhealthy",
                    "service": "prometheus-nexus",
                    "engine_health": "unknown",
                    "detail": f"status probe failed: {str(e)[:160]}",
                }

        @app.get("/dashboard")
        def dashboard():
            """Serve the advanced neural dashboard HTML."""
            import os
            html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
            if os.path.exists(html_path):
                from fastapi.responses import HTMLResponse
                with open(html_path, 'r', encoding='utf-8') as f:
                    return HTMLResponse(content=f.read())
            return {"error": "Dashboard not found"}

        @app.get("/api/v1/dashboard/static/{filename}")
        def dashboard_static(filename: str):
            """Serve dashboard static assets (css/js)."""
            import os
            static_dir = os.path.join(os.path.dirname(__file__), "dashboard_static")
            safe = os.path.basename(filename)
            path = os.path.join(static_dir, safe)
            if not os.path.exists(path):
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=404, content={"error": "not found"})
            from fastapi.responses import FileResponse
            ctype = "text/css" if safe.endswith(".css") else "application/javascript"
            return FileResponse(path, media_type=ctype)

        @app.get("/api/v1/monitor/detail")
        def monitor_detail():
            """最细粒度监控快照: 单机制级 invoke_count/effect/error/status +
            沉默机制 + 路由接管 + 动态层 + 突触修剪 + 系统指标 + 管道统计.
            """
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            nx = getattr(self.omega, "nexus", None)
            if not nx:
                raise HTTPException(status_code=503, detail="Nexus not initialized")
            with nx._lock:
                mechs = {}
                for name, e in nx._mechanisms.items():
                    mechs[name] = {
                        "category": e.get("category"),
                        "status": e.get("status"),
                        "is_dynamic": e.get("is_dynamic", False),
                        "invoke_count": e.get("invoke_count", 0),
                        "error_count": e.get("error_count", 0),
                        "effect": round(e.get("effect", 0.0), 4) if e.get("effect") else None,
                        "last_invoked": e.get("last_invoked"),
                    }
                snap = nx.get_monitor_snapshot()
            # 系统指标(实时资源, 用 psutil; SystemMonitor 是历史指标统计, 正交)
            sys_metrics = {}
            try:
                import psutil
                proc = psutil.Process()
                sys_metrics = {
                    "cpu_percent": psutil.cpu_percent(interval=0.1),
                    "memory_percent": psutil.virtual_memory().percent,
                    "memory_available_mb": round(psutil.virtual_memory().available / 1024 / 1024, 1),
                    "memory_used_mb": round(psutil.virtual_memory().used / 1024 / 1024, 1),
                    "disk_percent": psutil.disk_usage("/").percent,
                    "process_memory_mb": round(proc.memory_info().rss / 1024 / 1024, 1),
                    "thread_count": proc.num_threads(),
                }
            except Exception as e:
                sys_metrics = {"error": str(e)[:100]}
            # SystemMonitor 历史指标统计(正交, 附在 system.stats)
            sysmon = getattr(self.omega, "monitor", None)
            if sysmon is not None and hasattr(sysmon, "get_stats"):
                try:
                    sys_metrics["monitor_stats"] = sysmon.get_stats()
                except Exception:
                    pass

            pipes = {}
            for pn, pv in nx._pipelines.items():
                pipes[pn] = {"runs": pv.get("runs", 0), "failures": pv.get("failures", 0),
                             "last_run": pv.get("last_run")}
            return {
                "snapshot": snap,
                "mechanisms": mechs,
                "system": sys_metrics,
                "pipelines": pipes,
                "total_invocations": sum(nx._invoke_count.values()),
                "generated_at": time.time(),
            }

        @app.get("/api/v1/productions")
        def productions(since_minutes: float = 30):
            """产出视角: 返回最近 N 分钟内系统真实产出的东西.

            类型: knowledge(知识节点) / mechanism(T4编译机制) /
            belief(梦境信念) / reflection(反思结论) / evolution(进化) / prune(修剪)
            """
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            prods = getattr(self.omega, "_productions", [])
            cutoff = time.time() - since_minutes * 60
            recent = [p for p in prods if p.get("ts", 0) >= cutoff]
            by_type = {}
            for p in recent:
                by_type.setdefault(p["type"], 0)
                by_type[p["type"]] += 1
            return {
                "since_minutes": since_minutes,
                "total": len(recent),
                "by_type": by_type,
                "items": recent,
                "generated_at": time.time(),
            }

        @app.get("/api/v1/issues")
        def issues(since_minutes: float = 30):
            """运行问题视角: 返回最近 N 分钟内系统真实产生的 BUG/异常/关键WARNING.

            采集自 Omega._issues (由日志处理器 + 管道 except 填充).
            """
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            issuer = getattr(self.omega, "_get_issues", None)
            if issuer is None:
                return {"since_minutes": since_minutes, "total": 0, "by_level": {}, "items": []}
            return issuer(int(since_minutes))

        @app.get("/api/v1/skills")
        def skills():
            """技能提炼视角: 后见之明技能蒸馏的统计 (SEED + Agentic Proposing).

            返回 hindsight playbook 数、注册技能数、以及最近提炼的技能样本。
            """
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            pbs = getattr(self.omega.playbook_inheritance, "_playbooks", {})
            sc = getattr(self.omega.skill_claw, "_skills", {})
            hindsight_pb = [p for p in pbs.values() if "hindsight" in (p.tags or [])]
            hindsight_sk = [s for s in sc.values() if "hindsight" in (s.get("tags") or set())]
            samples = [{"type": s.get("name", "")[:30], "body": str(s.get("body", ""))[:50]}
                       for s in hindsight_sk[-5:]]
            return {
                "hindsight_playbooks": len(hindsight_pb),
                "hindsight_skills": len(hindsight_sk),
                "total_playbooks": len(pbs),
                "total_skills": len(sc),
                "distill_bonus": round(getattr(self.omega, "_distill_bonus", lambda: 0.0)(), 4),
                "samples": samples,
            }

        @app.get("/api/v1/status")
        def status():
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            s = self.omega.status()

            nx = getattr(self.omega, "nexus", None)
            nexus_stats = nx.get_stats() if nx else {}
            nexus_consumption = nx.get_consumption() if nx else {}
            return {
                "node_count": s.node_count,
                "edge_count": s.edge_count,
                "active_sessions": s.active_sessions,
                "uptime_seconds": s.uptime_seconds,
                "health": s.health,
                "version": s.version,
                "mechanisms": s.mechanisms,
                "details": s.details,
                "nexus": {
                    "stats": nexus_stats,
                    "consumption": nexus_consumption,
                },
            }

        @app.post("/api/v1/remember", response_model=PipelineResponse)
        def remember(req: RememberRequest):
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                node_id = self.omega.remember(
                    content=req.content,
                    utility=req.utility,
                    tags=req.tags,
                )
                if not node_id:
                    return PipelineResponse(
                        success=False, pipeline="remember",
                        data={"node_id": ""},
                        error="remember rejected by pipeline gates (low utility, safety filter, or dopamine threshold)",
                        duration_ms=(time.time() - t0) * 1000,
                    )
                return PipelineResponse(
                    success=True, pipeline="remember",
                    data={"node_id": node_id},
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                return PipelineResponse(
                    success=False, pipeline="remember",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        @app.post("/api/v1/recall", response_model=PipelineResponse)
        def recall(req: RecallRequest):
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                results = self.omega.recall(query=req.query, limit=req.limit)
                hits_data = []
                for h in results.hits:
                    hits_data.append({
                        "node_id": h.node_id,
                        "score": h.score,
                        "content": h.content[:500],
                        "snippet": h.snippet[:200] if h.snippet else "",
                    })
                return PipelineResponse(
                    success=True, pipeline="recall",
                    data={
                        "total_count": results.total_count,
                        "query": results.query,
                        "duration_ms": results.duration_ms,
                        "hits": hits_data,
                        "metadata": _safe_serialize(results.metadata or {}),
                    },
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                return PipelineResponse(
                    success=False, pipeline="recall",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        @app.post("/api/v1/evolve", response_model=PipelineResponse)
        def evolve(req: EvolveRequest):
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                outcome = self.omega.evolve(
                    context=req.context,
                    branch=req.branch,
                    confidence=req.confidence,
                )
                return PipelineResponse(
                    success=True, pipeline="evolve",
                    data={
                        "result": outcome.result.value if hasattr(outcome.result, 'value') else str(outcome.result),
                        "fitness_before": outcome.fitness_before,
                        "fitness_after": outcome.fitness_after,
                        "duration_ms": outcome.duration_ms,
                        "details": outcome.details,
                        "metadata": _safe_serialize(outcome.metadata or {}),
                    },
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                import traceback
                logger.error("evolve failed: %s\n%s", e, traceback.format_exc())
                return PipelineResponse(
                    success=False, pipeline="evolve",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        @app.post("/api/v1/learn", response_model=PipelineResponse)
        def learn(req: LearnRequest):
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                result = self.omega.learn(
                    source=req.source,
                    query=req.query,
                    max_results=req.max_results,
                )
                # Guard: coroutine leak from scanner (pre-existing bug)
                if hasattr(result, '__await__'):
                    return PipelineResponse(
                        success=False, pipeline="learn",
                        error=f"Scanner returned coroutine for source={req.source} (async leak)",
                        duration_ms=(time.time() - t0) * 1000,
                    )
                # Omega.learn may return a dict or a list depending on state
                if isinstance(result, dict):
                    data = result
                elif isinstance(result, list):
                    data = {"items": result, "count": len(result)}
                else:
                    data = {"result": str(result)}
                # Skip _safe_serialize for learn — the nested diagnostics dict
                # can contain mixed types that trigger 'list' object has no 'get'
                return PipelineResponse(
                    success=True, pipeline="learn",
                    data=data,
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                return PipelineResponse(
                    success=False, pipeline="learn",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        @app.post("/api/v1/reflect", response_model=PipelineResponse)
        def reflect(req: ReflectRequest):
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                result = self.omega.reflect(context=req.context)
                return PipelineResponse(
                    success=True, pipeline="reflect",
                    data=_safe_serialize(result),
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                return PipelineResponse(
                    success=False, pipeline="reflect",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        @app.post("/api/v1/dream", response_model=PipelineResponse)
        def dream(req: DreamRequest):
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                result = self.omega.dream_cycle(branch=req.branch)
                return PipelineResponse(
                    success=True, pipeline="dream",
                    data={
                        "patterns_found": result.patterns_found,
                        "beliefs_synthesized": result.beliefs_synthesized,
                        "connections_discovered": result.connections_discovered,
                        "insights": result.insights,
                        "dream_data": _safe_serialize(getattr(result, 'dream_data', {})),
                    },
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                return PipelineResponse(
                    success=False, pipeline="dream",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        @app.post("/api/v1/maintain", response_model=PipelineResponse)
        def maintain():
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                result = self.omega.maintain()
                return PipelineResponse(
                    success=True, pipeline="maintain",
                    data=_safe_serialize(result),
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                return PipelineResponse(
                    success=False, pipeline="maintain",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        @app.post("/api/v1/branch/create")
        def branch_create(req: BranchCreateRequest):
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            self.omega.branch_create(name=req.name, parent=req.parent)
            return {"success": True, "branch": req.name, "parent": req.parent}

        @app.post("/api/v1/branch/merge")
        def branch_merge(req: BranchMergeRequest):
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            write_id = self.omega.branch_merge(source=req.source, target=req.target)
            return {"success": True, "write_id": write_id}

        @app.get("/api/v1/branch/list")
        def branch_list():
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            branches = self.omega.branch_list()
            return {"branches": branches}

        @app.post("/api/v1/report_usage", response_model=PipelineResponse)
        def report_usage(req: ReportUsageRequest):
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                # 自动注册未注册的节点（反沉默失败）
                self.omega.utility_tracker.register(req.node_id)
                if req.was_useful:
                    self.omega.utility_tracker.record_reference(req.node_id)
                else:
                    self.omega.utility_tracker.record_negative_reference(req.node_id)
                return PipelineResponse(
                    success=True, pipeline="report_usage",
                    data={"node_id": req.node_id, "was_useful": req.was_useful},
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                return PipelineResponse(
                    success=False, pipeline="report_usage",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        # ── Node CRUD Endpoints ─────────────────────────────────

        @app.delete("/api/v1/nodes/{node_id}", response_model=PipelineResponse)
        def delete_node(node_id: str):
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                self.omega.store.delete_node(node_id)
                return PipelineResponse(
                    success=True, pipeline="delete_node",
                    data={"node_id": node_id, "deleted": True},
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                return PipelineResponse(
                    success=False, pipeline="delete_node",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        @app.patch("/api/v1/nodes/{node_id}", response_model=PipelineResponse)
        def update_node(node_id: str, req: UpdateNodeRequest):
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                node = self.omega.store.read_node(node_id)
                if node is None:
                    return PipelineResponse(
                        success=False, pipeline="update_node",
                        error=f"Node {node_id} not found",
                        duration_ms=(time.time() - t0) * 1000,
                    )
                if req.content:
                    node.content = req.content
                if req.utility >= 0:
                    node.utility = req.utility
                result = self.omega.store.update_node(node)
                return PipelineResponse(
                    success=result.success, pipeline="update_node",
                    data={"node_id": node_id, "updated": result.success},
                    error=result.reason if not result.success else None,
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                return PipelineResponse(
                    success=False, pipeline="update_node",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        @app.get("/api/v1/nodes/{node_id}", response_model=PipelineResponse)
        def read_node(node_id: str):
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                node = self.omega.store.read_node(node_id)
                if node is None:
                    return PipelineResponse(
                        success=False, pipeline="read_node",
                        error=f"Node {node_id} not found",
                        duration_ms=(time.time() - t0) * 1000,
                    )
                return PipelineResponse(
                    success=True, pipeline="read_node",
                    data=_safe_serialize(node),
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                return PipelineResponse(
                    success=False, pipeline="read_node",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        @app.post("/api/v1/nodes/search", response_model=PipelineResponse)
        def search_nodes(req: NodeSearchRequest):
            t0 = time.time()
            try:
                if not self.omega:
                    raise HTTPException(status_code=503, detail="Omega not initialized")
                results = self.omega.store.search(
                    query=req.query or None,
                    limit=req.limit,
                )
                hits_data = _safe_serialize(results) if results else []
                return PipelineResponse(
                    success=True, pipeline="search",
                    data={"hits": hits_data, "total": len(hits_data) if isinstance(hits_data, list) else 0},
                    duration_ms=(time.time() - t0) * 1000,
                )
            except Exception as e:
                return PipelineResponse(
                    success=False, pipeline="search",
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                )

        # ── Nervous System Endpoints ───────────────────────────

        @app.get("/api/v1/nervous/cns")
        def nervous_cns():
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            try:
                return _safe_serialize(self.omega.cns.get_state())
            except Exception as e:
                return {"error": str(e)}

        @app.get("/api/v1/nervous/cc")
        def nervous_cc():
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            try:
                return _safe_serialize(self.omega.cerebral_cortex.get_insights())
            except Exception as e:
                return {"error": str(e)}

        @app.get("/api/v1/nervous/ar")
        def nervous_ar():
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            try:
                return _safe_serialize(self.omega.autonomic_regulator.get_stats())
            except Exception as e:
                return {"error": str(e)}

        # ── V3.2 G1: 全机制端点 (Agent 调用 Ultra 所有机制+工具) ──────────

        @app.get("/api/v1/mechanisms", response_model=PipelineResponse)
        def list_mechanisms():
            """列出所有机制(含激活态) + 叠加态候选 [P1-b]."""
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            try:
                reg = self.omega.mechanism_registry
                return PipelineResponse(
                    success=True, pipeline="mechanisms",
                    data={
                        "enabled": reg.get_enabled(),
                        "stats": reg.get_stats(),
                        "superposed": reg.get_superposed_names(),
                    },
                    duration_ms=0.0,
                )
            except Exception as e:
                return PipelineResponse(success=False, pipeline="mechanisms", error=str(e))

        @app.post("/api/v1/mechanisms/invoke", response_model=PipelineResponse)
        def invoke_mechanism(req: dict):
            """真执行一个激活机制(D2 沙箱编译 draft_code) [V2.2]."""
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            try:
                name = req.get("name")
                ctx = req.get("context", {})
                result = self.omega.mechanism_registry.invoke(name, ctx)
                # 机制效用反馈(若请求带 effect) [V2.3 P0-a]
                if "effect" in req:
                    self.omega.mechanism_registry.record_mechanism_effect(name, float(req["effect"]))
                return PipelineResponse(success=True, pipeline="invoke", data=result)
            except Exception as e:
                return PipelineResponse(success=False, pipeline="invoke", error=str(e))

        @app.post("/api/v1/t3/extract", response_model=PipelineResponse)
        def t3_extract(req: dict):
            """T3 GitHub 机制提取轨 — 复用 Agent LLM 编译 [V3.0 G2]."""
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            try:
                source = req.get("source", "github")
                query = req.get("query", "")
                result = self.omega.mechanism_extractor.extract(source=source, query=query)
                return PipelineResponse(success=True, pipeline="t3_extract", data=result)
            except Exception as e:
                return PipelineResponse(success=False, pipeline="t3_extract", error=str(e))

        @app.post("/api/v1/t4/compile", response_model=PipelineResponse)
        def t4_compile(req: dict):
            """T4 论文编译轨 — 复用 Agent LLM 编译机制草案 [V3.0 G2]."""
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            try:
                arxiv_id = req.get("arxiv_id", "")
                title = req.get("title", "")
                mech = self.omega.mechanism_compiler.compile(arxiv_id, paper_title=title)
                if mech is None:
                    return PipelineResponse(success=False, pipeline="t4_compile",
                                            error="compile returned None (LLM unavailable or parse fail)")
                return PipelineResponse(
                    success=True, pipeline="t4_compile",
                    data={"name": mech.name, "draft_code_len": len(mech.draft_code or ""),
                          "target_location": str(mech.target_location)},
                )
            except Exception as e:
                return PipelineResponse(success=False, pipeline="t4_compile", error=str(e))

        @app.post("/api/v1/ruminate", response_model=PipelineResponse)
        def ruminate(req: dict):
            """温故知新 — 跨模态对齐/效用重评估 [V2.4 P1-c]."""
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            try:
                mode = req.get("mode", "full")
                res = self.omega.rumination_engine.ruminate(mode=mode, force=req.get("force", True))
                return PipelineResponse(
                    success=True, pipeline="ruminate",
                    data={"relearned": res.relearned, "utility_raised": res.utility_raised,
                          "routed": res.routed_nodes, "deleted": res.deleted_nodes},
                )
            except Exception as e:
                return PipelineResponse(success=False, pipeline="ruminate", error=str(e))

        @app.post("/api/v1/evolve/chain", response_model=PipelineResponse)
        def evolve_chain(req: dict):
            """进化 + 返回链完整性追踪(V2.3 P0-b chain_trace)."""
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            try:
                out = self.omega.evolve(context=req.get("context", ""))
                return PipelineResponse(
                    success=True, pipeline="evolve",
                    data={
                        "result": out.result.value if hasattr(out.result, "value") else str(out.result),
                        "chain_complete": out.metadata.get("chain_complete"),
                        "chain_trace": out.metadata.get("chain_trace"),
                        "chain_missing": out.metadata.get("chain_missing_stages"),
                        "fitness_before": out.fitness_before, "fitness_after": out.fitness_after,
                    },
                )
            except Exception as e:
                return PipelineResponse(success=False, pipeline="evolve", error=str(e))

        @app.get("/api/v1/utility/report", response_model=PipelineResponse)
        def utility_report():
            """效用追踪真实信号(D3 锚) — Agent 可据此诊断记忆健康."""
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            try:
                avgs = self.omega.utility_tracker.get_all_averages()
                return PipelineResponse(
                    success=True, pipeline="utility",
                    data={"node_count": len(avgs),
                          "global_utility": sum(avgs.values()) / len(avgs) if avgs else 0.5,
                          "samples": dict(list(avgs.items())[:20])},
                )
            except Exception as e:
                return PipelineResponse(success=False, pipeline="utility", error=str(e))

        @app.get("/api/v1/dashboard/summary", response_model=PipelineResponse)
        def dashboard_summary():
            """高级 Dashboard 聚合端点 — 一次性返回所有面板数据(减少前端请求)."""
            if not self.omega:
                raise HTTPException(status_code=503, detail="Omega not initialized")
            try:
                o = self.omega
                summary: dict = {}

                # ── 机制层 (V2.2/V2.3) ──
                reg = o.mechanism_registry
                mstats = reg.get_stats()
                # 机制状态分布(active/pending/compiled/extracted)
                status_dist = {}
                effect_list = []
                for nm, e in reg._mechanisms.items():
                    st = e.get("status", "unknown")
                    status_dist[st] = status_dist.get(st, 0) + 1
                    if e.get("effect_mean") is not None:
                        effect_list.append({"name": nm, "effect": round(e["effect_mean"], 3)})
                summary["mechanisms"] = {
                    "total": mstats.get("registered", 0),
                    "enabled": mstats.get("enabled", 0),
                    "status_dist": status_dist,
                    "superposed": reg.get_superposed_names(),
                    "prune_candidates": len(reg.get_prune_candidates()),
                    "top_effects": sorted(effect_list, key=lambda x: x["effect"])[:10],
                }

                # ── 进化层 (T1-T4 + chain) ──
                ev_stats = {}
                try:
                    ev_stats = o.evolution_engine.get_stats()
                except Exception:
                    pass
                summary["evolution"] = {
                    "engine_stats": ev_stats,
                    "last_chain": o._telemetry.get("evolve") if hasattr(o, "_telemetry") else None,
                    "gene_specs": len(getattr(o.evolution_engine, "_gene_specs", {})),
                }

                # ── 记忆层 (utility + 节点类型分布) ──
                node_count = 0
                try:
                    node_count = o.store.get_node_count()
                except Exception:
                    pass
                util_global = 0.5
                type_dist = {}
                try:
                    avgs = o.utility_tracker.get_all_averages()
                    util_global = sum(avgs.values()) / len(avgs) if avgs else 0.5
                    # 节点类型分布
                    from prometheus_nexus.foundation.schema import NodeType
                    for nt in NodeType:
                        try:
                            cnt = len(o.store.get_nodes_by_type(nt, limit=100000))
                            if cnt > 0:
                                type_dist[nt.value] = cnt
                        except Exception:
                            continue
                except Exception:
                    pass
                summary["memory"] = {
                    "node_count": node_count,
                    "global_utility": round(util_global, 4),
                    "type_distribution": type_dist,
                }

                # ── 适应度分解 (B1 三维可见性) ──
                fit_detail = {}
                try:
                    o._compute_fitness()  # 触发计算, 填充 _last_fitness_detail
                    fit_detail = getattr(o, "_last_fitness_detail", {}) or {}
                except Exception:
                    pass
                summary["fitness_detail"] = fit_detail

                # ── 机制消费率聚合 (方案Y: 覆盖全 6 类载体) ──
                try:
                    cons = o.get_mechanism_consumption()
                except Exception:
                    cons = {}
                summary["mechanism_consumption"] = cons

                # ── 外部知识源健康体检 (Agent-Reach doctor 哲学) ──
                try:
                    source_health = o.knowledge_scanner.probe_sources()
                except Exception:
                    source_health = {}
                summary["source_health"] = source_health

                # ── 反刍(温故知新)状态 (修复监控对反刍失明) ──
                try:
                    rstats = o.rumination_engine.get_stats()
                    due = o.rumination_engine.next_rumination_due()
                    summary["rumination"] = {
                        "last_full": rstats.get("last_full", 0.0),
                        "last_incremental": rstats.get("last_incremental", 0.0),
                        "history_len": rstats.get("history_len", 0),
                        "next_mode": due.get("mode", "skip"),
                        "seconds_to_full": due.get("seconds_to_full", 0),
                        "seconds_to_incremental": due.get("seconds_to_incremental", 0),
                    }
                    # ── 事件总线健康 (调用错误 + 孤岛模块检测) ──
                    try:
                        bus = getattr(o, "event_bus", None)
                        if bus is not None and hasattr(bus, "get_stats"):
                            bs = bus.get_stats()
                            # 孤岛 topic: 发布过(published_topics) 但无订阅者(_subscribers 无/空)
                            island_topics = []
                            try:
                                pub_topics = getattr(bus, "_published_topics", set()) or set()
                                subs = getattr(bus, "_subscribers", {}) or {}
                                for topic in pub_topics:
                                    if topic == "#":
                                        continue
                                    if not subs.get(topic):
                                        island_topics.append(topic)
                            except Exception:
                                pass
                            summary["event_bus"] = {
                                "published": bs.get("published", 0),
                                "delivered": bs.get("delivered", 0),
                                "failed": bs.get("failed", 0),
                                "dead_letters": bs.get("dead_letters", 0),
                                "topics": bs.get("topics", 0),
                                "island_topics": island_topics,  # 无订阅者的事件类型 = 孤岛模块
                                "recent_dead": [
                                    d.get("event", {}).get("type", "?") for d in (bs.get("_dead_letters", []) if isinstance(bs.get("_dead_letters"), list) else [])[:5]
                                ],
                            }
                    except Exception:
                        summary["event_bus"] = {}
                    # ── 学习到的论文 (从 store PAPER 节点动态聚合, 反映真实 arxiv 学习) ──
                    try:
                        from prometheus_nexus.foundation.store import NodeType
                        paper_nodes = o.store.get_nodes_by_type(NodeType.PAPER, limit=20) if o.store else []
                        learned_papers = [{
                            "title": (n.content or "")[:80],
                            "utility": round(getattr(n, "utility", 0.0), 3),
                            "url": getattr(n, "url", "") or "",
                        } for n in paper_nodes]
                        summary["learned_papers"] = learned_papers
                    except Exception:
                        summary["learned_papers"] = []
                except Exception:
                    summary["rumination"] = {}

                # ── 孤岛机制根因分类 (Tier 1: 把噪音变可行动清单) ──
                try:
                    cons = o.get_mechanism_consumption()
                    summary["mechanism_categories"] = {
                        "silent_by_category": cons.get("silent_by_category", {}),
                        "silent_count": cons.get("silent_count", 0),
                        "rate": cons.get("rate", 0.0),
                    }
                except Exception:
                    summary["mechanism_categories"] = {}

                # ── 过程层健康 (Tier 1 LLM-dark + Tier 3 资源/信号) ──
                try:
                    summary["pipeline_health"] = o.get_pipeline_health()
                except Exception:
                    summary["pipeline_health"] = {}

                # ── 语义相关性 (Tier 3: 是否在学垃圾) + 依赖深度 (传递性孤岛) ──
                try:
                    summary["semantic_health"] = o.get_semantic_health()
                except Exception:
                    summary["semantic_health"] = {}
                try:
                    summary["dependency_depth"] = o.get_dependency_depth()
                except Exception:
                    summary["dependency_depth"] = {}

                # ── 宿主接入层 (V3 G3 多 Agent 隔离) ──
                host_id = "none"
                try:
                    host_id = getattr(o.host, "host_id", "none")
                except Exception:
                    pass
                summary["agents"] = {
                    "active_host": host_id,
                    "adapter_type": type(o.host).__name__ if hasattr(o, "host") else "none",
                }

                # ── 论文借力映射 (V2.3/V2.4 六篇) ──
                summary["papers"] = [
                    {"arxiv": "2505.18605", "title": "Rethink Causal Mask Attention for VL",
                     "ultra": "recall future-aware", "rating": "PARTIAL", "ver": "V2.4 P1-a"},
                    {"arxiv": "2606.23885", "title": "Modality-Mutual Attention (HeRA)",
                     "ultra": "跨NodeType拓扑对齐", "rating": "PARTIAL", "ver": "V2.4 P1-c"},
                    {"arxiv": "2506.07851", "title": "Learning to Focus (Grad Token Pruning)",
                     "ultra": "机制主动剪枝", "rating": "MATCH", "ver": "V2.3 P0-a"},
                    {"arxiv": "2501.12004", "title": "Overlapped-Frame Fusion (Speech)",
                     "ultra": "时间邻域融合", "rating": "PARTIAL", "ver": "V2.4b P1-d"},
                    {"arxiv": "2505.14684", "title": "Mind the Gap (Thought Leap)",
                     "ultra": "evolve链完整性", "rating": "MATCH", "ver": "V2.3 P0-b"},
                    {"arxiv": "2604.06374", "title": "Reasoning by Superposition",
                     "ultra": "机制叠加态候选", "rating": "MATCH", "ver": "V2.4 P1-b"},
                ]

                return PipelineResponse(success=True, pipeline="dashboard_summary", data=summary)
            except Exception as e:
                return PipelineResponse(success=False, pipeline="dashboard_summary", error=str(e))

        @app.on_event("startup")
        def startup():
            if not self.omega:
                from prometheus_nexus.life import Omega
                self.omega = Omega(db_path=self.db_path)
                logger.info("Omega initialized on startup (db=%s)", self.db_path)

    def start(self, omega: Optional[Any] = None, background: bool = True):
        """Start the API server.

        Args:
            omega: Pre-initialized Omega instance (optional).
            background: If True, run in background thread.

        Raises:
            RuntimeError: if the server is already running, or if it fails to
                become ready (e.g. port already in use, startup crashed) within
                the readiness window. A "started but not actually listening"
                state is treated as a failure so callers/tests get a real
                signal instead of a silent false-positive.
        """
        if self.is_running:
            raise RuntimeError(
                f"Nexus API server already running on {self.host}:{self.port}; "
                f"call stop() before starting again"
            )
        if omega:
            self.omega = omega
        elif not self.omega:
            from prometheus_nexus.life import Omega
            self.omega = Omega(db_path=self.db_path)

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=False,
        )
        server = uvicorn.Server(config)
        self._uvicorn_server = server

        if background:
            self._server_thread = threading.Thread(target=server.run, daemon=True)
            self._server_thread.start()
            logger.info("Nexus API server starting on %s:%d (background)", self.host, self.port)
            # Wait for server to be ready. Fail-LOUD on timeout: never return
            # "success" while nothing is actually listening (a silent false start
            # would mislead keepalive/monitor and any caller of start()).
            import time as _time
            for _ in range(30):
                try:
                    import urllib.request
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}/api/v1/health", timeout=1
                    )
                    logger.info("Nexus API server ready on %s:%d", self.host, self.port)
                    return
                except Exception:
                    _time.sleep(0.2)
            raise RuntimeError(
                f"Nexus API server failed to become ready on {self.host}:{self.port} "
                f"within the readiness window (port in use or startup crashed?)"
            )
        else:
            server.run()

    def stop(self):
        """Stop the server and close Omega.

        Actually terminates the uvicorn server (signals graceful exit and joins
        the run thread) so the port is released. A no-op stop that leaves the
        HTTP server running would give a false "stopped" signal and leak the
        listening port across tests / restarts.
        """
        uvicorn_server = getattr(self, "_uvicorn_server", None)
        if uvicorn_server is not None:
            try:
                uvicorn_server.should_exit = True
            except Exception:
                pass
        thread = self._server_thread
        if thread is not None:
            thread.join(timeout=5)
            self._server_thread = None
        if self.omega:
            self.omega.close()
            self.omega = None
        logger.info("Nexus API server stopped")

    @property
    def is_running(self) -> bool:
        return self._server_thread is not None and self._server_thread.is_alive()


def _safe_serialize(obj: Any) -> Any:
    """Recursively serialize an object to JSON-safe types."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_safe_serialize(item) for item in obj]
    if isinstance(obj, BaseModel):
        return _safe_serialize(obj.model_dump())
    # Dataclass (DreamResult, etc.)
    if hasattr(obj, '__dataclass_fields__'):
        return _safe_serialize({k: getattr(obj, k) for k in obj.__dataclass_fields__})
    if hasattr(obj, '__dict__'):
        return _safe_serialize({k: v for k, v in obj.__dict__.items() if not k.startswith('_')})
    if hasattr(obj, 'value'):
        return obj.value
    return str(obj)


# ── CLI Entry ────────────────────────────────────────────────────────


def main():
    """Run the Nexus API server from command line."""
    import argparse

    parser = argparse.ArgumentParser(description="Prometheus Nexus API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9200, help="Port to listen on")
    parser.add_argument("--db-path", default=None, help="SQLite database path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    server = UltraAPIServer(host=args.host, port=args.port, db_path=args.db_path)
    server.start(background=False)


if __name__ == "__main__":
    main()
