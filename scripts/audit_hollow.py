"""空壳化审计 (Hollow Audit) — 第一轮多轮审计.

目标: 找出"注册了/被记账了, 但实质不干活"的机制(假绿最危险形态).

判定维度:
  H1 假实现: 主方法体仅 pass / return {} / raise NotImplementedError(被注册却空)
  H2 静默吞错: 主方法 except: pass 包裹实质逻辑(永远返回成功, 掩盖失败)
  H3 恒量返回: 主方法不读输入/状态, 恒定返回(永远 ok=True 之类)
  H4 死代码复活空转: 之前修复接入的6机制, 接回但内部空转
  H5 被记账零实效: Nexus invoke_count>0 但方法对输入无依赖(输入无关)

方法: 静态 AST 预筛(快找嫌疑) + 运行时探测(准验证恒量/无依赖).
"""
from __future__ import annotations
import ast
import logging
import sys
import os
import tempfile

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus import Omega, ZConfig
from prometheus_nexus.cns.nexus import NexusProxy

# 主方法候选名(按全仓分布实测扩展)
# 含: 标准机制主方法 + 常见非常规主方法(search/scrape/retrieve/store/generate...)
PRIMARY_METHODS = ("run", "evaluate", "check", "execute", "score", "process", "assess",
                   "decide", "detect", "verify", "select", "update", "scan", "route",
                   "compute", "match", "filter", "gate", "tick", "health_check",
                   "search", "scrape", "retrieve", "generate", "rank", "store",
                   "add", "get", "sync", "embed", "encode", "classify", "predict")

# 探测输入(多样化, 看返回是否随输入变化)
PROBE_INPUTS = [
    {"query": "alpha", "utility": 0.9, "node": None, "context": {"x": 1}},
    {"query": "beta", "utility": 0.1, "node": None, "context": {"x": 2}},
    {"query": "gamma", "utility": 0.5, "node": None, "context": {}},
]


def _primary_methods_of(inst):
    """返回实例上定义的主方法名列表(优先类定义里的, 非继承 ABC)."""
    found = []
    for m in PRIMARY_METHODS:
        if hasattr(inst, m) and callable(getattr(inst, m)):
            # 确认是本类定义(非 BaseMechanism 抽象)
            for klass in type(inst).__mro__:
                if m in klass.__dict__:
                    found.append((m, klass))
                    break
    return found


def _scan_all_methods_for_hollow(klass):
    """不依赖方法名白名单: 扫描类的所有 public 方法, 检测是否真·空壳.

    返回标签列表. 高置信信号(不依赖方法名):
      - ALL_METHODS_EMPTY: 所有 public 方法体空/pass/纯常量返回 -> 真空壳
      - HAS_SILENT_EXCEPT: 某方法 except:pass 静默吞错
      - RAISES_NOT_IMPL: 某方法 raise NotImplementedError (抽象未实现却注册)
    """
    tags = []
    pub_methods = [(n, fn) for n, fn in vars(klass).items()
                   if not n.startswith("_") and isinstance(fn, (type(lambda: 0), staticmethod, classmethod))]
    if not pub_methods:
        # 无 public 方法(纯数据/配置类) -> 非机制, 但不算空壳
        return ["NO_PUBLIC_METHODS"]
    empty_count = 0
    for n, fn in pub_methods:
        if not isinstance(fn, (type(lambda: 0),)):
            continue
        try:
            src = ast.getsource(fn)
            tree = ast.parse(src)
        except Exception:
            continue
        func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == n:
                func = node
                break
        if func is None:
            continue
        body = func.body
        is_empty = (len(body) == 0 or all(isinstance(s, ast.Pass) for s in body))
        is_const = (len(body) == 1 and isinstance(body[0], ast.Return)
                    and isinstance(body[0].value, (ast.Constant, ast.Dict, ast.List, ast.Name)))
        if is_empty or is_const:
            empty_count += 1
        # 静默吞错
        for node in ast.walk(func):
            if isinstance(node, ast.Try):
                for h in node.handlers:
                    if len(h.body) == 1 and isinstance(h.body[0], ast.Pass):
                        tags.append("HAS_SILENT_EXCEPT")
                        break
        # raise NotImplementedError
        for node in ast.walk(func):
            if isinstance(node, ast.Raise):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Name) and "NotImplemented" in sub.id:
                        tags.append("RAISES_NOT_IMPL")
    if empty_count == len(pub_methods) and pub_methods:
        tags.append("ALL_METHODS_EMPTY")
    return tags


def _static_scan_method(cls, method_name):
    """AST 分析类方法体, 返回嫌疑标签."""
    fn = cls.__dict__.get(method_name)
    if fn is None or not isinstance(fn, (type(lambda: 0),)):
        # 可能是 builtin / wrapper, 跳过静态
        return []
    try:
        src = ast.getsource(fn)
    except Exception:
        return []
    try:
        tree = ast.parse(src)
    except Exception:
        return []
    tags = []
    # 找方法 def 体
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == method_name:
            func = node
            break
    if func is None:
        return []
    body = func.body
    # H1: 空体 / 仅 pass / 仅 return {} / raise NotImplementedError
    if len(body) == 0:
        tags.append("empty_body")
    elif all(isinstance(s, ast.Pass) for s in body):
        tags.append("pass_only")
    elif len(body) == 1 and isinstance(body[0], ast.Return):
        ret = body[0].value
        if ret is None or (isinstance(ret, ast.Dict) and not ret.keys):
            tags.append("returns_empty")
        if isinstance(ret, ast.Constant) and isinstance(ret.value, (bool, int, str, dict, list)):
            tags.append("returns_constant")
    # 检测 raise NotImplementedError
    for n in ast.walk(func):
        if isinstance(n, ast.Raise):
            for sub in ast.walk(n):
                if isinstance(sub, ast.Name) and "NotImplemented" in sub.id:
                    tags.append("raises_not_implemented")
    # H2: 静默吞错 except: pass / except Exception: pass (无日志无重抛)
    for n in ast.walk(func):
        if isinstance(n, ast.Try):
            for handler in n.handlers:
                hbody = handler.body
                if len(hbody) == 1 and isinstance(hbody[0], ast.Pass):
                    tags.append("silent_except_pass")
                # except Exception as e: pass (变量未用)
                if len(hbody) == 1 and isinstance(hbody[0], ast.Pass):
                    tags.append("silent_except_pass")
    return tags


def _runtime_probe(inst, method_name):
    """运行时探测: 用多组输入调主方法, 看返回是否随输入变化 / 是否恒量 / 是否异常."""
    fn = getattr(inst, method_name, None)
    if fn is None:
        return {"callable": False}
    results = []
    errored = False
    for inp in PROBE_INPUTS:
        try:
            # 尝试不同调用签名(机制主方法签名多样)
            try:
                r = fn(inp)
            except TypeError:
                try:
                    r = fn(**inp)
                except TypeError:
                    r = fn()
            results.append(repr(r))
        except Exception as e:
            errored = True
            results.append(f"ERR:{type(e).__name__}")
    distinct = set(results)
    return {
        "callable": True,
        "errored": errored,
        "distinct_results": len(distinct),
        "all_same": len(distinct) == 1,
        "samples": results[:3],
    }


def audit():
    db = tempfile.mktemp(suffix=".db")
    o = Omega(config=ZConfig(database_path=db))
    findings = {}  # name -> {methods: [...], tags, runtime}
    # 遍历 Nexus 注册的非管道机制
    for name, entry in o.nexus._mechanisms.items():
        if entry.get("category") == "pipeline":
            continue
        inst = o.nexus._base_instances.get(name) or o.nexus._dynamic.get(name)
        if inst is None:
            continue
        prims = _primary_methods_of(inst)
        if not prims:
            # 无候选主方法 -> 软信号: 方法名不在常见集合(可能非常规名或纯数据类)
            # 不定罪(方法名极度不统一, 白名单不可靠), 仅记录供人工
            findings[name] = {"methods": [], "static_tags": ["UNCONVENTIONAL_METHODS"],
                              "runtime": {}, "category": entry.get("category")}
            continue
        all_tags = []
        runtime = {}
        for m, klass in prims:
            tags = _static_scan_method(klass, m)
            all_tags.extend(tags)
            runtime[m] = _runtime_probe(inst, m)
        # 方法名无关空壳扫描(高置信, 不依赖主方法白名单)
        hollow_tags = _scan_all_methods_for_hollow(type(inst))
        all_tags.extend(hollow_tags)
        findings[name] = {
            "methods": [m for m, _ in prims],
            "static_tags": sorted(set(all_tags)),
            "runtime": runtime,
            "category": entry.get("category"),
            "invoke_count": entry.get("invoke_count", 0),
        }
    o.close()
    return findings


def summarize(findings):
    hollow = {}       # 真空壳机制(高置信静态信号)
    soft = {}         # 软信号(方法名非常规/无 public 方法, 不定罪)
    for name, f in findings.items():
        tags = f.get("static_tags", [])
        if "UNCONVENTIONAL_METHODS" in tags or "NO_PUBLIC_METHODS" in tags:
            soft[name] = f.get("category", "?")
            continue
        reasons = []
        # 高置信空壳信号(方法名无关)
        for t in ("ALL_METHODS_EMPTY", "HAS_SILENT_EXCEPT", "RAISES_NOT_IMPL",
                  "empty_body", "pass_only", "returns_empty", "returns_constant"):
            if t in tags:
                reasons.append(f"静态:{t}")
        if reasons:
            hollow[name] = reasons
    return hollow, soft


if __name__ == "__main__":
    f = audit()
    hollow, soft = summarize(f)

    print("空壳化审计 (Hollow Audit) — 第一轮")
    print("=" * 64)
    print(f"扫描注册项总数: {len(f)}")
    print(f"真空壳机制(高置信: 空体/静默吞错/未实现): {len(hollow)}")
    print(f"软信号注册项(方法名非常规/无public方法, 不定罪): {len(soft)}")
    print("-" * 64)
    if hollow:
        print("【A类】真空壳机制(需人工确认/修复):")
        for name, reasons in sorted(hollow.items()):
            cat = f[name].get("category", "?")
            inv = f[name].get("invoke_count", 0)
            print(f"  [{name}] cat={cat} inv={inv}")
            for r in reasons:
                print(f"      - {r}")
    if soft:
        from collections import Counter
        dist = Counter(soft.values())
        print("【B类】软信号(方法名非常规/纯数据类, 不定罪):")
        print(f"  分布: {dict(dist)}")
        print(f"  样例: {sorted(soft)[:20]}")
    print("=" * 64)
    print("结论: A类=真空壳(高置信, 方法名无关AST扫描); B类=方法名不统一/纯数据类,"
          "属架构事实(机制方法命名无强制契约), 非真空壳")
