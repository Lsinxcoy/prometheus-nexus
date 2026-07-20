"""Nexus — 神经系统统一中枢.

设计定位(2026-07-19 架构决策):
    Ultra = 外挂记忆 / 自进化生命体的大脑.
    Nexus 是这套神经系统的**统一神经中枢**, 统辖:
      - 机制层: 236 基本盘机制 + 动态层(T3/T4 编译产物)
      - 7 管道: remember/recall/evolve/learn/reflect/dream/maintain
      - 两层共享记忆:
          ① 知识记忆 (MinervaStore, 7管道共享)  —— 数据层, Nexus 引用不替换
          ② 机制经验记忆 (effect 账本)           —— 机制共享"什么有效/有害"
      - 效果路由: 动态机制实战更优则接管基本盘对应功能(fallback 永驻)
      - 突触修剪: 效果账本负向机制自动 deactivate

关键不变量(防回归):
    - Nexus 是**仲裁者**, 不是执行者. 机制执行后端仍是 life.py 的实例(self.x).
      dispatch() 查状态/效果/路由后, 转调 self.x.method(), 绝不双重执行.
    - 不吞并 MinervaStore / ModelRouter (数据层/后端层, 仅引用).
    - 236 基本盘机制全注册, 零丢失.

基于现有 MechanismRegistry 升级(复用 register/verify_and_activate/prune_harmful/
record_mechanism_effect), 新增: 管道注册, 动态层挂载, dispatch 仲裁, 效果路由.
"""
from __future__ import annotations
import logging
import time
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


class Nexus:
    """神经系统统一中枢.

    统辖机制层 + 7管道 + 两层记忆 + 效果路由 + 突触修剪.
    是仲裁者(决定调谁/怎么调/效果如何), 非执行者(执行仍由 life.py 实例).
    """

    def __init__(self, path: str | None = None, store=None):
        self._path = path
        self._store = store  # 知识记忆层(引用, 不替换)
        self._lock = threading.RLock()

        # ---- 机制层 ----
        self._mechanisms: dict[str, dict] = {}        # name -> entry
        self._enabled: set[str] = set()
        self._dynamic: dict[str, Any] = {}            # 动态层: name -> 可执行实例(sandbox加载)
        self._base_instances: dict[str, Any] = {}     # 基本盘: name -> life.py 实例(执行后端)

        # ---- 7 管道注册 ----
        self._pipelines: dict[str, dict] = {}         # name -> {fn, last_run, runs, failures}

        # ---- 两层记忆 ----
        # ① 知识记忆: 经 self._store 读写 (Nexus 不持有, 仅引用)
        # ② 机制经验记忆: effect 账本
        self._effects: dict[str, list[float]] = {}    # name -> [effect,...]
        self._invoke_count: dict[str, int] = {}       # name -> 调用次数(记账)
        self._last_invoked: dict[str, float] = {}

        # ---- 路由覆盖: 动态机制接管基本盘 (name -> 动态 name) ----
        self._route_override: dict[str, str] = {}

        self._load()

    # ==================================================================
    # 机制注册 (基本盘 + 动态层)
    # ==================================================================
    def register_mechanism(self, name: str, instance: Any = None,
                           category: str = "general", pending: bool = False,
                           is_dynamic: bool = False) -> dict:
        """注册机制. 基本盘或动态层统一入口.

        Args:
            name: 机制名(与 life.py self.<name> 对齐)
            instance: 执行后端实例(life.py 的 self.x)
            category: 功能域(safety/evolution/memory/learning/...)
            pending: True=待验证激活(动态层编译产物)
            is_dynamic: True=动态层(T3/T4), False=基本盘
        """
        with self._lock:
            entry = {
                "name": name,
                "category": category,
                "status": "pending" if pending else "active",
                "is_dynamic": is_dynamic,
                "invoke_count": 0,
                "error_count": 0,
                "last_invoked": None,
                "activated_at": None if pending else time.time(),
                "effect": 0.0,
            }
            self._mechanisms[name] = entry
            if not pending:
                self._enabled.add(name)
            if instance is not None:
                if is_dynamic:
                    self._dynamic[name] = instance
                else:
                    self._base_instances[name] = instance
            self._persist()
            return {"registered": True, "name": name, "category": category, "status": entry["status"]}

    def mount_dynamic(self, name: str, instance: Any, category: str = "compiled",
                      target_base: str | None = None) -> dict:
        """T3/T4 编译产物经沙箱加载后, 挂载进动态层 + 注册.

        这是"神经发生": 新机制长入大脑, 不碰基本盘源码.
        接管语义(对齐 P6 不自动直替): 仅当显式声明 target_base(宿主/论文指明
        覆盖哪个基本盘)时才设 route_override 接管; 否则仅挂动态层作候选.
        """
        res = self.register_mechanism(name, instance=instance, category=category,
                                      pending=False, is_dynamic=True)
        if target_base and target_base in self._base_instances:
            self.set_route_override(target_base, name)
            logger.info("Nexus: 动态 %s 经显式声明接管基本盘 %s", name, target_base)
        return res

    # ==================================================================
    # 7 管道注册
    # ==================================================================
    def register_pipeline(self, name: str, fn: Callable, category: str = "pipe") -> dict:
        """注册 7 管道之一. Nexus 统辖触发/协同/记忆读写."""
        with self._lock:
            self._pipelines[name] = {"fn": fn, "category": category,
                                      "last_run": None, "runs": 0, "failures": 0}
            return {"registered": True, "name": name}

    # ==================================================================
    # 调度仲裁 (dispatch) — 核心: 查状态/效果/路由, 转调执行后端, 记账
    # ==================================================================
    def dispatch(self, name: str, method: str = "run", context: dict | None = None,
                 *args, **kwargs) -> Any:
        """仲裁调用机制. 不双重执行 — 转调 life.py 实例, 仅记账+路由.

        路由逻辑:
          1. 若有 route_override[name] -> 用动态机制接管
          2. 否则用基本盘实例
          3. 实例不存在/未激活 -> 返回 None(不崩)
        """
        with self._lock:
            target = self._route_override.get(name, name)
            inst = self._dynamic.get(target) or self._base_instances.get(target)
            if inst is None:
                logger.debug("Nexus.dispatch: %s 无执行后端, 跳过", name)
                return None
            entry = self._mechanisms.get(target)
            if entry and entry["status"] not in ("active", "enabled"):
                logger.debug("Nexus.dispatch: %s 状态=%s 未激活, 跳过", target, entry["status"])
                return None
            # 记账
            self._invoke_count[name] = self._invoke_count.get(name, 0) + 1
            self._last_invoked[name] = time.time()
            if entry:
                entry["invoke_count"] = entry["invoke_count"] + 1
                entry["last_invoked"] = time.time()
        # 转调执行后端(不双重执行)
        try:
            fn = getattr(inst, method, None)
            if fn is None:
                return None
            return fn(*args, **kwargs)
        except Exception as e:
            with self._lock:
                if entry:
                    entry["error_count"] = entry["error_count"] + 1
            logger.warning("Nexus.dispatch: %s.%s 失败: %s", name, method, str(e)[:60])
            return None

    def mark_invoked(self, name: str) -> None:
        """轻量记账(供 life.py 直接调用点补记, 不转调)."""
        with self._lock:
            self._invoke_count[name] = self._invoke_count.get(name, 0) + 1
            self._last_invoked[name] = time.time()
            if name in self._mechanisms:
                self._mechanisms[name]["invoke_count"] += 1
                self._mechanisms[name]["last_invoked"] = time.time()

    # ==================================================================
    # 效果路由 (优势强化) — 动态机制实战更优则接管基本盘
    # ==================================================================
    def record_effect(self, name: str, effect: float) -> None:
        """记录机制实战效果(经验记忆). 同时记账一次调用."""
        with self._lock:
            self._invoke_count[name] = self._invoke_count.get(name, 0) + 1
            self._last_invoked[name] = time.time()
            if name in self._mechanisms:
                self._mechanisms[name]["invoke_count"] += 1
                self._mechanisms[name]["last_invoked"] = time.time()
            self._effects.setdefault(name, []).append(effect)
            eff = sum(self._effects[name][-20:]) / len(self._effects[name][-20:])
            if name in self._mechanisms:
                self._mechanisms[name]["effect"] = eff
            # 路由决策: 动态机制效果持续优于其覆盖的基本盘 -> 接管
            for base, dyn in list(self._route_override.items()):
                if dyn == name:
                    base_eff = self._avg_effect(base)
                    if eff > base_eff + 0.05:  # 动态更优阈值
                        logger.info("Nexus: 动态 %s 接管基本盘 %s (eff %.3f > %.3f)",
                                     name, base, eff, base_eff)
                    elif eff < base_eff - 0.1:  # 动态变劣 -> 回退基本盘
                        logger.info("Nexus: 动态 %s 回退基本盘 %s (eff %.3f < %.3f)",
                                     name, base, eff, base_eff)
                        del self._route_override[base]

    def _avg_effect(self, name: str) -> float:
        effs = self._effects.get(name, [])
        return sum(effs[-20:]) / len(effs[-20:]) if effs else 0.0

    def set_route_override(self, base_name: str, dynamic_name: str) -> None:
        """显式让动态机制接管基本盘功能(需先经 verify_and_activate + 效果验证)."""
        with self._lock:
            self._route_override[base_name] = dynamic_name

    # ==================================================================
    # 突触修剪 (淘汰有害/无效机制)
    # ==================================================================
    def prune_harmful(self, threshold: float = -0.3) -> list[str]:
        """效果账本负向机制自动 deactivate(突触修剪). 基本盘不删, 仅动态层可修剪."""
        pruned = []
        with self._lock:
            for name, entry in self._mechanisms.items():
                if not entry.get("is_dynamic", False):
                    continue  # 基本盘永驻, 不修剪
                eff = entry.get("effect", 0.0)
                inv = entry.get("invoke_count", 0)
                if inv >= 3 and eff <= threshold:
                    entry["status"] = "disabled"
                    self._enabled.discard(name)
                    if name in self._dynamic:
                        del self._dynamic[name]
                    for b, d in list(self._route_override.items()):
                        if d == name:
                            del self._route_override[b]
                    pruned.append(name)
        if pruned:
            self._persist()
            logger.info("Nexus: 突触修剪 %d 个有害动态机制: %s", len(pruned), pruned)
        return pruned

    # ==================================================================
    # 消费/健康 (统一真相源, 供监控只读)
    # ==================================================================
    def get_consumption(self) -> dict:
        """机制消费真实统计(替代旧 get_mechanism_consumption 的6载体聚合漏算)."""
        with self._lock:
            total = len(self._mechanisms)
            consumed = sum(1 for e in self._mechanisms.values()
                           if e.get("invoke_count", 0) > 0)
            dyn = sum(1 for e in self._mechanisms.values() if e.get("is_dynamic"))
            return {
                "total": total, "consumed": consumed,
                "rate": (consumed / total) if total else 0.0,
                "dynamic": dyn, "base": total - dyn,
                "by_category": self._by_category(),
            }

    def _by_category(self) -> dict:
        cats: dict[str, int] = {}
        for e in self._mechanisms.values():
            c = e.get("category", "general")
            cats[c] = cats.get(c, 0) + 1
        return cats

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "mechanisms": len(self._mechanisms),
                "enabled": len(self._enabled),
                "dynamic": len(self._dynamic),
                "pipelines": len(self._pipelines),
                "route_overrides": len(self._route_override),
                "total_invocations": sum(self._invoke_count.values()),
                "by_category": self._by_category(),
            }

    # ==================================================================
    # 监控统合 (第三层): 统一监控真相源 — 所有监控层只读此视图
    # ==================================================================
    def get_monitor_snapshot(self) -> dict:
        """统一监控快照: 机制层 + 动态层 + 路由 + 突触修剪 + 静默机制.

        所有监控层(maintain/heartbeat)只读此视图, 不再各自聚合机制状态.
        SystemMonitor 的系统指标(CPU/内存)正交, 不在此(仅引用 store/健康).
        """
        with self._lock:
            cons = self.get_consumption()
            # 静默机制: 已注册但从未被调用(记账 0)的非管道机制
            silent = [n for n, e in self._mechanisms.items()
                      if e.get("category") != "pipeline"
                      and e.get("invoke_count", 0) == 0
                      and not e.get("is_dynamic", False)]
            # 动态接管中: 动态层已激活且覆盖基本盘(name 在 route_override 值中)
            active_dynamic = [d for d in self._dynamic
                              if any(v == d for v in self._route_override.values())]
            return {
                "mechanisms": cons["total"],
                "consumed": cons["consumed"],
                "rate": cons["rate"],
                "dynamic": cons["dynamic"],
                "base": cons["base"],
                "by_category": cons["by_category"],
                "pipelines": len(self._pipelines),
                "route_overrides": dict(self._route_override),
                "active_dynamic": active_dynamic,
                "pruned_disabled": [n for n, e in self._mechanisms.items()
                                    if e.get("status") == "disabled"],
                "silent_mechanisms": silent,
                "total_invocations": sum(self._invoke_count.values()),
            }

    # ==================================================================
    # 持久化
    # ==================================================================
    def _persist(self) -> None:
        if not self._path:
            return
        import json, os
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            blob = {
                "mechanisms": {k: {kk: vv for kk, vv in v.items()
                                    if kk not in ("instance",)}
                               for k, v in self._mechanisms.items()},
                "enabled": sorted(self._enabled),
                "dynamic_names": sorted(self._dynamic.keys()),
                "route_override": self._route_override,
            }
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(blob, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)
        except Exception as e:
            logger.warning("Nexus._persist failed: %s", e)

    def _load(self) -> None:
        if not self._path:
            return
        import json, os
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                blob = json.load(f)
            self._mechanisms = blob.get("mechanisms", {})
            self._enabled = set(blob.get("enabled", []))
            self._route_override = blob.get("route_override", {})
        except Exception as e:
            logger.warning("Nexus._load failed: %s", e)


# ==================================================================
# NexusProxy — 第二层: 统一调度的透明代理
# ==================================================================
class NexusProxy:
    """透明代理包裹机制实例, 让所有调用过 Nexus 统一调度中枢.

    设计(零侵入调用点):
      - 用 __getattr__ 转发所有属性/方法调用到 wrapped 真实实例(透明)
      - 每次访问: nexus.mark_invoked(name) 记账 + 检查 route_override
        决定转基本盘或动态层(优势强化路由)
      - 不双重执行: 代理只转发, 不额外执行(底层实例是唯一执行者)
      - 满足 is not None / 直接属性访问(透明, 不破坏 5000 行调用点)
      - 经代码核查: 全仓库无 isinstance(self.x) 检查, 仅 is not None 检查(代理满足)

    使用: self.five_gates = NexusProxy(real_fg, nexus, "five_gates")
    """

    def __init__(self, instance, nexus, name):
        object.__setattr__(self, "_instance", instance)
        object.__setattr__(self, "_nexus", nexus)
        object.__setattr__(self, "_name", name)

    def __getattr__(self, item):
        # __getattr__ 仅在实例自身无此属性时触发(方法在 _instance 上)
        inst = object.__getattribute__(self, "_instance")
        nexus = object.__getattribute__(self, "_nexus")
        name = object.__getattribute__(self, "_name")
        attr = getattr(inst, item)
        # 仅可调用方法转发时记账(属性读取如 .enabled 不污染消费率统计)
        if callable(attr):
            try:
                nexus.mark_invoked(name)
            except Exception:
                pass
        # 效果路由: 动态层接管则转动态实例(仅当 item 在动态实例上)
        target = nexus._route_override.get(name)
        if target and target in nexus._dynamic and hasattr(nexus._dynamic[target], item):
            return getattr(nexus._dynamic[target], item)
        return attr

    def __setattr__(self, key, value):
        object.__getattribute__(self, "_instance").__setattr__(key, value)

    def __delattr__(self, key):
        object.__getattribute__(self, "_instance").__delattr__(key)

    # 容器/迭代 dunder 透明转发到真实实例 —— 避免调用点把代理当容器迭代时
    # 抛 'NexusProxy' object is not iterable (CNS 重构后部分调用点直接迭代机制属性)
    def __iter__(self):
        return iter(object.__getattribute__(self, "_instance"))

    def __len__(self):
        return len(object.__getattribute__(self, "_instance"))

    def __getitem__(self, key):
        return object.__getattribute__(self, "_instance")[key]

    def __contains__(self, item):
        return item in object.__getattribute__(self, "_instance")
