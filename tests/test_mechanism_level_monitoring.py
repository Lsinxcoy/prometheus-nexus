"""机制级监控可见性测试.

用户诉求: 监控不能只查通道(接口通不通), 要查机制级静默/调用错误/孤岛模块.
否则长期运行产出虚假繁荣.

后端增强:
- get_mechanism_consumption 增加 silent_mechanisms/silent_count (注册但从未消费)
- event_bus 记录 published_topics, dashboard 用其检测孤岛 topic (发布过但无订阅者)

测试:
- get_mechanism_consumption 方法存在于 life 模块
- event_bus: publish 后 published_topics 含该 topic; 无订阅者 -> 孤岛可检测
- event_bus.get_stats 返回 failed/dead_letters/published
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_life_has_consumption_method():
    """life 模块应暴露 get_mechanism_consumption (聚合消费率 + 孤岛机制)."""
    import prometheus_nexus.life as life
    # 找任意含该方法的类(Omega/OmegaEngine 等)
    found = any("get_mechanism_consumption" in dir(cls)
                for cls in vars(life).values()
                if isinstance(cls, type))
    assert found, "life 模块应有类实现 get_mechanism_consumption"


def test_event_bus_island_detection():
    """发布过但无订阅者的 topic 应被识别为孤岛."""
    from prometheus_nexus.collaboration.event_bus import CIPEventBus
    bus = CIPEventBus()
    bus.publish("orphan_topic_x", {"v": 1})  # 无人订阅
    pub = getattr(bus, "_published_topics", set())
    subs = getattr(bus, "_subscribers", {})
    assert "orphan_topic_x" in pub, "发布的 topic 应记入 published_topics"
    assert not subs.get("orphan_topic_x"), "无订阅者 -> subscribers 里无/空"
    # 模拟监控 island 逻辑
    islands = [t for t in pub if t != "#" and not subs.get(t)]
    assert "orphan_topic_x" in islands, "孤岛 topic 应被检测出"


def test_event_bus_stats_shape():
    """event_bus.get_stats 返回 failed/dead_letters/published (调用错误检测基础)."""
    from prometheus_nexus.collaboration.event_bus import CIPEventBus
    bus = CIPEventBus()
    st = bus.get_stats()
    for k in ("published", "delivered", "failed", "dead_letters", "topics"):
        assert k in st, f"event_bus stats 缺 {k}"
