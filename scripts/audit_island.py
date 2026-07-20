"""孤岛机制审计 (Island Audit) — 第二轮多轮审计.

目标: 找出"被 Nexus 注册/记账, 但从不与其他机制或管道形成调用依赖"的孤岛.

孤岛维度(基于本仓真实调用图):
  - 入度孤岛: 没有任何管道/机制在代码里静态引用 self.<name> (grep 不到)
  - 出度孤岛: 机制内部不引用其他机制/store/event_bus (不与系统交互)
  - 运行时孤岛: 七管道跑完后 invoke_count 仍为 0 (从未被真实触发)

高置信判定: 静态入度=0 且 运行时 invoke_count=0 -> 真孤岛(死挂, 不参与任何流程)
中置信: 仅静态入度=0 (可能被动态 dispatch 按需调, 需人工确认)
低置信: 仅运行时 invoke_count=0 (可能依赖特定输入才触发)

注意:
  - dependencies 字段仅存在于 base_mechanism.meta(), Nexus 不建图, 故依赖图
    只能从静态 self.xxx 引用反推.
  - NexusProxy 仅包裹 227 个非管道机制; 部分机制经 dispatch 动态调用, 不入静态图.
"""
from __future__ import annotations
import ast
import logging
import os
import re
import sys
import tempfile
import subprocess

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def static_in_degree(mechanism_names):
    """扫描全仓 self.<name> 引用 + 注册表注册名引用, 返回入度.

    用 Python re 扫描(避免 grep PCRE 兼容问题).
    入度来源:
      1. self.<name> 直接引用(管道/机制直接调)
      2. registry.register("<name>", ...) / register_mechanism("<name>", ...)
         (本能层/注册表层间接调用, 不经 self.xxx)
    """
    pats_self = {n: re.compile(rf"self\.{re.escape(n)}(?![a-zA-Z0-9_])") for n in mechanism_names}
    pats_reg = {n: re.compile(rf"""register\(?["']{re.escape(n)}["']""") for n in mechanism_names}
    refs = {n: 0 for n in mechanism_names}
    py_files = []
    for root, _, files in os.walk(SRC):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))
    file_texts = []
    for fp in py_files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                file_texts.append(fh.read())
        except Exception:
            file_texts.append("")
    combined = "\n".join(file_texts)
    for n in mechanism_names:
        deg = 0
        # 排除机制自身定义/注册行(伪引用): self.name = 或 register("name", cls) 在自身文件
        # 这里用全局计数, 伪引用(定义/注册本身)通常 <2, 真调用 >=2; 保守计入
        deg += len(pats_self[n].findall(combined))
        deg += len(pats_reg[n].findall(combined))
        refs[n] = deg
    return refs


def static_out_degree(mechanism_names, omega):
    """扫描每个机制类源码, 统计它内部引用了多少其他机制(self.<other>)."""
    out_deg = {}
    for name in mechanism_names:
        inst = omega.nexus._base_instances.get(name) or omega.nexus._dynamic.get(name)
        if inst is None:
            out_deg[name] = 0
            continue
        klass = type(inst)
        try:
            src = ast.getsource(klass)
        except Exception:
            out_deg[name] = 0
            continue
        found = set()
        for m in re.finditer(r"self\.([a-zA-Z_][a-zA-Z0-9_]*)", src):
            ref = m.group(1)
            if ref in mechanism_names and ref != name:
                found.add(ref)
        out_deg[name] = len(found)
    return out_deg


def runtime_invoke_counts(omega):
    """返回 {name: invoke_count} 来自 Nexus 记账."""
    return {n: e.get("invoke_count", 0) for n, e in omega.nexus._mechanisms.items()}


def audit():
    from prometheus_nexus import Omega, ZConfig
    db = tempfile.mktemp(suffix=".db")
    o = Omega(config=ZConfig(database_path=db))

    mech_names = [n for n, e in o.nexus._mechanisms.items()
                  if e.get("category") != "pipeline"]

    in_deg = static_in_degree(mech_names)
    out_deg = static_out_degree(mech_names, o)

    # 注册表层持有(本能/技能经 registry 触发, 不走 self.xxx)
    registry_held = set()
    inst = getattr(o, "instincts", None)
    if inst is not None:
        reg = getattr(inst, "_instincts", None) or getattr(inst, "registry", None)
        if reg is not None:
            if isinstance(reg, list):
                # InstinctsRegistry._instincts: list[dict]
                for item in reg:
                    if isinstance(item, dict) and "name" in item:
                        registry_held.add(item["name"])
            elif hasattr(reg, "_map"):
                registry_held |= set(reg._map.keys())
            elif isinstance(reg, dict):
                registry_held |= set(reg.keys())
    sk = getattr(o, "skill_registry", None)
    if sk is not None:
        sm = getattr(sk, "_skill_map", None) or getattr(sk, "skills", None)
        if sm is not None and isinstance(sm, dict):
            registry_held |= set(sm.keys())

    # 跑七管道(真实触发, 让 Nexus 记账)
    for fn in ("remember", "recall", "learn", "evolve", "reflect", "dream_cycle", "maintain"):
        try:
            getattr(o, fn)(content="island audit probe", utility=0.8, tags=["audit"],
                           query="neural island test", max_results=1,
                           context="island audit", confidence=0.5)
        except TypeError:
            try:
                getattr(o, fn)()
            except Exception:
                pass
        except Exception:
            pass

    after = runtime_invoke_counts(o)
    o.close()
    return {
        "names": mech_names,
        "in_deg": in_deg,
        "out_deg": out_deg,
        "after": after,
        "registry_held": registry_held,
    }


def summarize(data):
    names = data["names"]
    in_deg = data["in_deg"]
    out_deg = data["out_deg"]
    after = data["after"]
    registry_held = data.get("registry_held", set())

    high = []      # 静态入度=0 且 运行时invoke=0 且 不在registry -> 真孤岛
    exempt = []    # 在registry持有(本能/技能范式, 非孤岛)
    mid = []       # 静态入度=0 但运行时被调
    low = []       # 有入度但运行时未触发
    islands = []
    for n in names:
        indeg = in_deg.get(n, 0)
        inv = after.get(n, 0)
        outdeg = out_deg.get(n, 0)
        is_island = indeg == 0 and outdeg == 0
        if n in registry_held:
            exempt.append(n)
            continue
        if indeg == 0 and inv == 0:
            high.append(n)
            islands.append((n, "双孤岛" if is_island else "入度孤岛"))
        elif indeg == 0 and inv > 0:
            mid.append(n)
        elif indeg > 0 and inv == 0:
            low.append(n)
    return high, mid, low, islands, exempt


if __name__ == "__main__":
    d = audit()
    high, mid, low, islands, exempt = summarize(d)
    print("=" * 64)
    print("孤岛机制审计 (Island Audit) — 第二轮")
    print("=" * 64)
    print(f"机制总数(非管道): {len(d['names'])}")
    print(f"【高置信真孤岛】静态入度=0 且 运行时invoke=0 且 不在注册表: {len(high)}")
    print(f"【注册表范式豁免】本能/技能经 registry 触发(非孤岛): {len(exempt)}")
    print(f"【中置信】静态入度=0 但运行时被调(可能动态dispatch): {len(mid)}")
    print(f"【低置信】有入度但运行时未被调(依赖特定输入): {len(low)}")
    print("-" * 64)
    if islands:
        print("真孤岛清单(建议审查/移除):")
        for n, kind in sorted(islands):
            indeg = d["in_deg"].get(n, 0)
            outdeg = d["out_deg"].get(n, 0)
            inv = d["after"].get(n, 0)
            print(f"  [{n}] {kind} in={indeg} out={outdeg} inv={inv}")
    if exempt:
        print(f"注册表范式豁免(非孤岛, 样例): {sorted(exempt)[:15]}")
    if mid:
        print("中置信(动态调用可能):", sorted(mid)[:20])
    if low:
        print("低置信(有入度未触发):", sorted(low)[:20])
    print("=" * 64)
    print(f"结论: 高置信真孤岛 {len(high)} 个(死挂, 不参与任何流程, 建议审查/移除)")
