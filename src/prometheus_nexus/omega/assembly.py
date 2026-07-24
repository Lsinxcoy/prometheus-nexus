"""omega 包 — Omega(上帝类)的装配/子系统外置层.

架构优化(真拆 life.py 第一步, 最高收益高风险项, 用户授权):
把 Omega.__init__ 里与"调度"解耦的装配逻辑外置到本包, 逐步收敛 5443 行上帝类。
本模块抽离 _nexus_register_all(机制注册 + 统一调度代理 + 注册表统合),
纯搬迁, 行为逐行不变。life.py 仅保留调度流程。

原则: 调度集中是上帝, 不可肢解; 只外置装配/器官, 不拆主循环。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register_all_mechanisms(self) -> None:
    """批量注册全部机制 + 7 管道进 Nexus(零丢失, 不破坏现有执行).

    原 life.py._nexus_register_all 的纯搬迁版本。设计: Nexus 是仲裁者,
    不替代 life.py 实例. 注册仅建立 '机制名 -> 执行后端 + 分类 + 记账' 映射。

    Args:
        self: Omega 实例(装配其 .nexus / .机制属性)
    """
    import inspect  # noqa: F401  (保留原 import, 未来扩展用)

    DOMAIN_MAP = {
        "safety": "safety", "evolution": "evolution", "memory": "memory",
        "learning": "learning", "lifecycle": "lifecycle", "loop": "loop",
        "execution": "execution", "harness": "harness", "integration": "integration",
        "monitor": "monitor", "cns": "cns", "foundation": "foundation",
        "skills": "skill", "reasoning": "reasoning", "model": "model",
    }
    registered = 0
    skipped = 0
    for attr, val in list(self.__dict__.items()):
        if attr.startswith("_") or attr in ("nexus", "mechanism_registry",
                                             "store", "event_bus", "host", "llm",
                                             "server", "monitor", "x_adapter", "y_adapter",
                                             "schema", "config", "curator", "skill_claw"):
            continue
        if val is None or not hasattr(val, "__class__"):
            continue
        module = getattr(val.__class__, "__module__", "") or ""
        domain = "general"
        for k, v in DOMAIN_MAP.items():
            if f".{k}." in f".{module}." or module.endswith(f".{k}"):
                domain = v
                break
        try:
            self.nexus.register_mechanism(attr, instance=val, category=domain)
            registered += 1
        except Exception as e:
            skipped += 1
            logger.debug("Nexus register %s skipped: %s", attr, str(e)[:40])
    # 7 管道注册(用真实方法名)
    pipe_methods = {}
    for pname in ("remember", "recall", "evolve", "learn", "reflect", "dream_cycle", "maintain"):
        fn = getattr(self, pname, None)
        if callable(fn):
            pipe_methods[pname] = fn
    for pname, fn in pipe_methods.items():
        self.nexus.register_pipeline(pname, fn)
        # 管道也注册进 _mechanisms(让消费率/记账口径一致), 不传实例(dispatch 不走管道)
        self.nexus.register_mechanism(pname, category="pipeline")
        # 包装: 管道调用时自动 mark_invoked(记账, 不双重执行)
        # 注意: 实例属性上的函数是裸函数, 不会自动绑定 self,
        # 必须用闭包捕获 self(外层 __init__ 的 self)
        _self = self
        orig = fn

        def _wrapped(*a, _orig=orig, _pn=pname, **kw):
            _self.nexus.mark_invoked(_pn)
            return _orig(*a, **kw)

        _wrapped.__name__ = pname
        setattr(self, pname, _wrapped)
    logger.info("Nexus: 注册机制 %d (跳过 %d), 7 管道已注册", registered, skipped)

    # 第二层: 统一调度 — 将已注册的机制实例包成 NexusProxy,
    # 所有调用透明过 Nexus(记账+效果路由), 零侵入 5000 行调用点.
    from prometheus_nexus.cns.nexus import NexusProxy

    proxied = 0
    for attr, entry in list(self.nexus._mechanisms.items()):
        if entry.get("category") == "pipeline":
            continue  # 管道是方法, 不代理
        inst = self.nexus._base_instances.get(attr)
        if inst is None:
            continue
        try:
            self.__dict__[attr] = NexusProxy(inst, self.nexus, attr)
            proxied += 1
        except Exception as e:
            logger.debug("Nexus proxy wrap %s skipped: %s", attr, str(e)[:40])
    logger.info("Nexus: 统一调度代理包裹 %d 个机制", proxied)

    # 第四层: 注册表统合 — SkillRegistry / InstinctsRegistry 同步进 Nexus 分类
    # (Nexus 成为统一分类视图; 原注册表保留不破坏)
    sk = getattr(self, "skill_registry", None)
    if sk is not None:
        for sk_name in getattr(sk, "_skill_map", {}):
            try:
                self.nexus.register_mechanism(sk_name, category="skill")
            except Exception:
                pass
    ins = getattr(self, "instincts", None)
    if ins is not None:
        for inst_entry in getattr(ins, "_instincts", []):
            in_name = inst_entry.get("name") if isinstance(inst_entry, dict) else None
            if in_name:
                try:
                    self.nexus.register_mechanism(in_name, category="instinct")
                except Exception:
                    pass
    logger.info("Nexus: 统合 Skill(%d)+Instinct(%d) 进分类视图",
                len(getattr(sk, "_skill_map", {})),
                len(getattr(ins, "_instincts", [])))
