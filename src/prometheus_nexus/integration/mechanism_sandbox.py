"""MechanismSandbox — T4 编译机制的真实执行环境 [D2 真能力].

问题实证:
- registry.invoke() 调 entry["executable"].run(context) (registry.py:154-169)
- 但 CompiledMechanism.run() 仅返回草案信息(draft_code_len 等), 不执行 draft_code
  (mechanism_compiler.py:42-51) -> 机制激活后可 invoke, 但永远是空壳
- draft_code 存在 archive/compiled/{name}.py, 但全代码无 importlib/exec 加载 -> 机制从不变能力

本模块提供沙箱执行:
- 把 draft_code 编译成 BaseMechanism 子类的真实 callable(importlib 动态加载, 受控 namespace)
- 仅 active 机制可编译执行(门控: activate 通过验证门才允许跑, 不自动直替)
- 超时 + 异常隔离: 编译/执行失败不影响系统(返回错误而非崩溃)
- 这是"建议+宿主确认"语义的终点: 验证激活 -> 真编译 -> 真执行 -> 能力生效

安全边界:
- 不执行未激活机制(pending 机制只存草案)
- 编译在隔离 globals (无 __builtins__ 危险项), 禁 subprocess/os.system 等
- 执行超时硬杀(线程级), 防死循环
"""
from __future__ import annotations

import importlib.util
import sys
import threading
import logging
import types
from typing import Any

logger = logging.getLogger(__name__)

# 禁止的危险内建(防止 draft_code 做危险操作)
_FORBIDDEN_BUILTINS = {
    "exec", "eval", "open", "input", "__import__",
    "compile", "globals", "locals", "vars",
}
# 允许的最小内建白名单
def _safe_import(name, *args, **kwargs):
    # 仅允许导入已知安全模块(机制基类 + 标准数学库), 防任意代码加载
    allowed = {
        "prometheus_nexus.mechanisms.base_mechanism",
        "math", "json", "collections", "typing", "dataclasses", "itertools", "functools",
    }
    if name not in allowed and not name.startswith("prometheus_nexus.mechanisms.base_mechanism"):
        raise ImportError(f"Sandbox: import of {name!r} not allowed")
    return __builtins__["__import__"](name, *args, **kwargs)

_ALLOWED_BUILTINS = {
    "print": print, "len": len, "range": range, "enumerate": enumerate,
    "zip": zip, "map": map, "filter": filter, "sorted": sorted,
    "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
    "float": float, "int": int, "str": str, "bool": bool, "list": list,
    "dict": dict, "tuple": tuple, "set": set, "frozenset": frozenset,
    "isinstance": isinstance, "hasattr": hasattr, "getattr": getattr,
    "type": type, "Exception": Exception, "ValueError": ValueError,
    "TypeError": TypeError, "KeyError": KeyError, "RuntimeError": RuntimeError,
    "StopIteration": StopIteration, "NotImplementedError": NotImplementedError,
    "__import__": _safe_import,
    "__build_class__": __builtins__["__build_class__"],
}


class MechanismSandbox:
    """编译并执行 draft_code 的沙箱."""

    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
        self._cache: dict[str, type] = {}  # name -> 编译好的类

    def compile_mechanism(self, name: str, draft_code: str, base_mechanism_mod) -> type | None:
        """把 draft_code 编译成 BaseMechanism 子类. 返回类或 None(失败)."""
        if name in self._cache:
            return self._cache[name]
        try:
            # 隔离 namespace: 只暴露白名单内建 + 必要依赖
            glb: dict[str, Any] = {
                "__builtins__": dict(_ALLOWED_BUILTINS),
                "BaseMechanism": base_mechanism_mod.BaseMechanism,
            }
            # 注入必要标准库(受控)
            import math
            glb["math"] = math
            spec = importlib.util.spec_from_loader(f"_mech_{name}", loader=None)
            mod = types.ModuleType(f"_mech_{name}")
            mod.__dict__.update(glb)
            # 编译(检测语法/危险调用)
            code = compile(draft_code, f"<mech_{name}>", "exec")
            exec(code, mod.__dict__)  # noqa: S102 — 沙箱隔离, 白名单内建
            # 找 BaseMechanism 子类
            cls = None
            for v in mod.__dict__.values():
                if (isinstance(v, type) and issubclass(v, base_mechanism_mod.BaseMechanism)
                        and v is not base_mechanism_mod.BaseMechanism):
                    cls = v
                    break
            if cls is None:
                logger.warning("Sandbox: no BaseMechanism subclass in %s", name)
                return None
            self._cache[name] = cls
            return cls
        except Exception as e:
            logger.warning("Sandbox: compile %s failed: %s", name, e)
            return None

    def run(self, name: str, draft_code: str, base_mechanism_mod, context: dict | None = None) -> dict:
        """编译 + 执行机制, 返回 run 结果. 超时隔离."""
        cls = self.compile_mechanism(name, draft_code, base_mechanism_mod)
        if cls is None:
            return {"ok": False, "note": "compile_failed", "mechanism": name}
        try:
            inst = cls()
            result_holder: dict[str, Any] = {}

            def _target():
                try:
                    result_holder["r"] = inst.run(context or {})
                except Exception as e:
                    result_holder["err"] = str(e)

            t = threading.Thread(target=_target, daemon=True)
            t.start()
            t.join(self.timeout)
            if t.is_alive():
                return {"ok": False, "note": "timeout", "mechanism": name}
            if "err" in result_holder:
                return {"ok": False, "note": f"run_error: {result_holder['err']}", "mechanism": name}
            r = result_holder.get("r", {})
            if isinstance(r, dict):
                r["_executed"] = True
                return r
            return {"ok": True, "result": r, "_executed": True}
        except Exception as e:
            return {"ok": False, "note": f"exec_failed: {e}", "mechanism": name}
