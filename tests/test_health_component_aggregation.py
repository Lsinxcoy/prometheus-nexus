"""Cycle 27 — 监控盲区修复: _compute_health 必须聚合组件健康。

根因: life.py 的 status() 已安全采集 12 个组件的健康细节(含错误捕获),
但 _compute_health() 完全忽略这些细节, 仅看 store 节点数 + equilibrium
告警级别。后果: 任一组件探测失败(抛错/未初始化)时, 引擎健康仍被报为
"healthy", 看门狗(ultra_keepalive 的 is_up 只看 status=='healthy')与
监控对真实退化不可见 —— 典型监控盲区, 且部分抵消了 cycle7 让 health
端点暴露 engine_health 的修复。

本测试注入组件失败, 断言引擎健康正确降级, 且不破坏 equilibrium 优先信号
与空库/异常兜底。

注意: 所有实例方法打桩均经 monkeypatch(自动回滚), 避免污染共享单例
(如 store/equilibrium) 拖累后续测试(尤其 test_empty_store_short_circuits)。
"""
from prometheus_nexus.foundation.schema import AlertLevel
import prometheus_nexus.life as life_mod


def _omega():
    return life_mod.Omega()


def _raiser(msg):
    def _f():
        raise RuntimeError(msg)
    return _f


def test_healthy_when_all_components_ok(monkeypatch):
    o = _omega()
    monkeypatch.setattr(o.store, "get_node_count", lambda: 5)
    monkeypatch.setattr(o.equilibrium, "get_alert_level", lambda: AlertLevel.GREEN)
    # 全部组件正常 -> healthy
    assert o._compute_health() == "healthy"
    assert o.status().health == "healthy"


def test_single_component_failure_downgrades_to_degraded(monkeypatch):
    o = _omega()
    monkeypatch.setattr(o.store, "get_node_count", lambda: 5)
    monkeypatch.setattr(o.equilibrium, "get_alert_level", lambda: AlertLevel.GREEN)
    # 仅 evolution_engine 失败 -> 应降级 (原先会被隐藏为 healthy)
    monkeypatch.setattr(o.evolution_engine, "get_stats", _raiser("boom"))
    assert o._compute_health() == "degraded"
    st = o.status()
    assert st.health == "degraded"
    # 失败组件在 details 中以 error 暴露, 便于定位
    assert st.details["evolution_engine"]["error"] == "boom"


def test_many_component_failures_escalate_to_critical(monkeypatch):
    o = _omega()
    monkeypatch.setattr(o.store, "get_node_count", lambda: 5)
    monkeypatch.setattr(o.equilibrium, "get_alert_level", lambda: AlertLevel.GREEN)
    # 超过阈值(HEALTH_CRITICAL_COMPONENT_FAILURES=3)个组件失败 -> critical
    for attr in ("evolution_engine", "five_gates", "dopamine", "constitution"):
        monkeypatch.setattr(getattr(o, attr), "get_stats", _raiser(f"{attr} down"))
    assert o._compute_health() == "critical"


def test_equilibrium_red_overrides_component_health(monkeypatch):
    o = _omega()
    monkeypatch.setattr(o.store, "get_node_count", lambda: 5)
    monkeypatch.setattr(o.equilibrium, "get_alert_level", lambda: AlertLevel.RED)
    # equilibrium RED 是最优先信号, 即便组件全绿仍 critical
    assert o._compute_health() == "critical"


def test_equilibrium_orange_yields_degraded(monkeypatch):
    o = _omega()
    monkeypatch.setattr(o.store, "get_node_count", lambda: 5)
    monkeypatch.setattr(o.equilibrium, "get_alert_level", lambda: AlertLevel.ORANGE)
    assert o._compute_health() == "degraded"


def test_status_health_consistent_with_compute(monkeypatch):
    o = _omega()
    monkeypatch.setattr(o.store, "get_node_count", lambda: 5)
    monkeypatch.setattr(o.equilibrium, "get_alert_level", lambda: AlertLevel.GREEN)
    assert o.status().health == o._compute_health()


def test_empty_store_short_circuits(monkeypatch):
    o = _omega()  # 全新临时库, 节点为 0
    # 显式绑定 node_count=0: 即使 store 是跨测试共享单例(被其他测试写入节点),
    # 本测试也确定性验证"空库 -> empty"短路逻辑, 不受全局状态泄漏影响
    monkeypatch.setattr(o.store, "get_node_count", lambda: 0)
    monkeypatch.setattr(o.equilibrium, "get_alert_level", lambda: AlertLevel.GREEN)
    assert o._compute_health() == "empty"
