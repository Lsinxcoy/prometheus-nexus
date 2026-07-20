"""CIPEventBus — 事件总线与Pub/Sub系统.

基于:
- "Event-Driven Architecture with Pub/Sub" (Richardson, 2017)
  - 发布/订阅: 多对多事件分发
  - 事件过滤: 按类型/优先级过滤
  - 事件持久化: 历史事件回放
  - 死信队列: 处理失败的订阅

算法:
    publish(event):
        1. 时间戳和ID
        2. 查找匹配订阅者
        3. 按优先级排序
        4. 异步分发
    
    subscribe(topic, handler):
        1. 注册主题+处理器
        2. 设置优先级
        3. 返回订阅ID

复杂度:
    publish(): O(S log S) S=订阅者数
    subscribe(): O(1)
"""
from __future__ import annotations
import time
import logging

logger = logging.getLogger(__name__)

import hashlib
from collections import defaultdict


class CIPEventBus:
    """事件总线 — 发布/订阅模式实现.
    
    支持主题订阅、事件过滤、历史回放和死信处理.
    """
    
    def __init__(self, max_history: int = 500, dead_letter_limit: int = 100):
        """初始化事件总线.
        
        Args:
            max_history: 最大历史事件数
            dead_letter_limit: 死信队列限制
        """
        self._max_history = max_history
        self._dead_letter_limit = dead_letter_limit
        
        self._subscribers: dict[str, list[dict]] = defaultdict(list)
        self._history: list[dict] = []
        self._dead_letters: list[dict] = []
        self._published_topics: set[str] = set()  # 孤岛检测: 发布过但无订阅者的 topic
        self._stats = {"published": 0, "delivered": 0, "failed": 0}
    
    def subscribe(self, topic: str, handler: callable,
                  priority: float = 0.5,
                  filter_fn: callable | None = None) -> str:
        """订阅主题.
        
        Args:
            topic: 主题名
            handler: 处理函数(event) -> result
            priority: 优先级 [0, 1]
            filter_fn: 过滤器(event) -> bool
        
        Returns:
            str: 订阅ID
        """
        sub_id = hashlib.md5(f"{topic}:{id(handler)}:{time.time()}".encode()).hexdigest()[:8]
        
        self._subscribers[topic].append({
            "id": sub_id,
            "handler": handler,
            "priority": priority,
            "filter_fn": filter_fn,
            "created_at": time.time(),
        })
        
        # 按优先级排序
        self._subscribers[topic].sort(key=lambda x: x["priority"], reverse=True)
        
        return sub_id
    
    def unsubscribe(self, sub_id: str) -> bool:
        """取消订阅.
        
        Args:
            sub_id: 订阅ID
        
        Returns:
            bool: 是否成功
        """
        for topic in list(self._subscribers.keys()):
            subs = self._subscribers[topic]
            for i, sub in enumerate(subs):
                if sub["id"] == sub_id:
                    subs.pop(i)
                    if not subs:
                        del self._subscribers[topic]
                    return True
        return False
    
    def publish(self, topic: str | dict, event: dict | None = None, priority: str = "normal") -> dict:
        """发布事件.
        
        Args:
            topic: 主题名 (或事件字典, 兼容旧版单参调用)
            event: 事件数据 (当 topic 为 str 时必填)
            priority: 优先级(high/normal/low)
        
        Returns:
            dict: 发布报告
        """
        # 兼容旧版: publish(event_dict) — 从字典中提取 topic
        if isinstance(topic, dict):
            event = topic
            topic = event.get("type", "general")
        if event is None:
            event = {}

        # 防腐扁平化 (A1 教训): 部分 publish 误将业务字段嵌套进二级
        #   {"type": "x_completed", "data": {"field": v}} —— 总线会把整个
        #   event 包进 enriched_event["data"]，导致 Telemetry/订阅者从
        #   event.data.field 读取时落到 event.data.data.field (静默 None)。
        #   此处自动把二级 data 的字段提升到顶层，兼容正确写法
        #   (字段已在顶层) 与错误嵌套写法，二者皆可被正确解析。
        if isinstance(event, dict) and isinstance(event.get("data"), dict) \
                and set(event.keys()) <= {"type", "data"}:
            nested = event.pop("data")
            event.update(nested)

        event_id = hashlib.md5(f"{topic}:{time.time()}:{event}".encode()).hexdigest()[:12]
        
        enriched_event = {
            "id": event_id,
            "topic": topic,
            "priority": priority,
            "data": event,
            "published_at": time.time(),
        }
        
        self._stats["published"] += 1
        self._published_topics.add(topic)  # 记录所有发布过的 topic (孤岛检测用)
        
        # 查找匹配订阅者
        subscribers = self._subscribers.get(topic, [])
        wildcard_subs = self._subscribers.get("#", [])  # 通配符订阅
        all_subs = subscribers + wildcard_subs
        
        delivered = 0
        failed = 0
        delivery_log = []
        
        for sub in all_subs:
            # 过滤 (filter_fn 异常必须隔离: 不能让单个订阅者的过滤器崩溃整个
            # fan-out, 否则该事件之后所有订阅者被静默跳过 —— 与 cycle 6 handler
            # 故障隔离同一原则。原实现 filter_fn 调用在 try 之外, 一旦 filter
            # 抛异常会直接冒泡出 publish() 并中断循环, 既崩发布方又丢后续订阅者)。
            if sub["filter_fn"]:
                try:
                    if not sub["filter_fn"](enriched_event):
                        continue
                except Exception as fe:
                    failed += 1
                    delivery_log.append({
                        "sub_id": sub["id"],
                        "status": "filter_error",
                        "error": str(fe)[:100],
                    })
                    logger.error(
                        "CIPEventBus: filter_fn failed | topic=%r event_id=%s sub_id=%s: %s",
                        topic, event_id, sub["id"], fe,
                    )
                    continue
            
            # 执行处理器
            try:
                result = sub["handler"](enriched_event)
                delivered += 1
                delivery_log.append({
                    "sub_id": sub["id"],
                    "status": "delivered",
                    "result_summary": str(result)[:100] if result else None,
                })
            except Exception as e:
                failed += 1
                delivery_log.append({
                    "sub_id": sub["id"],
                    "status": "failed",
                    "error": str(e)[:100],
                })
                self._dead_letters.append({
                    "event": enriched_event,
                    "sub_id": sub["id"],
                    "error": str(e)[:200],
                    "ts": time.time(),
                })
                # 事件总线死角修复: 订阅者处理失败必须暴露到日志, 否则失败被静默
                # 记入死信队列而无人知晓 (监控盲区)。event_bus 处于关键生命周期
                # 路径 (capability_consumed / *_completed 等), 静默失败 = 子系统
                # 不可见的退化 —— 与 cycle1 安全门 fail-closed / cycle3 收件箱
                # 裸 pass 同一类"表面正常、真实丢失"的根因。
                logger.error(
                    "CIPEventBus: handler failed | topic=%r event_id=%s sub_id=%s: %s",
                    topic, event_id, sub["id"], e,
                )

        # 限制死信队列: 超出上限时仅保留最近的 dead_letter_limit 条, 并显式
        # 记录被丢弃的死信 (避免无声丢失 —— 原实现既丢弃又无任何日志)。
        if len(self._dead_letters) > self._dead_letter_limit:
            dropped = len(self._dead_letters) - self._dead_letter_limit
            self._dead_letters = self._dead_letters[-self._dead_letter_limit:]
            logger.warning(
                "CIPEventBus: dead-letter queue exceeded limit=%d, dropped %d oldest dead letters",
                self._dead_letter_limit, dropped,
            )
        
        self._stats["delivered"] += delivered
        self._stats["failed"] += failed
        
        # 保存到历史
        self._history.append({
            "event_id": event_id,
            "topic": topic,
            "delivered": delivered,
            "failed": failed,
            "ts": time.time(),
        })
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history // 2:]
        
        return {
            "event_id": event_id,
            "topic": topic,
            "subscribers_notified": len(all_subs),
            "delivered": delivered,
            "failed": failed,
            "delivery_log": delivery_log,
        }
    
    def get_history(self, topic: str | None = None, limit: int = 50) -> list[dict]:
        """获取事件历史.
        
        Args:
            topic: 主题过滤
            limit: 返回数量
        
        Returns:
            list: 历史事件
        """
        history = self._history
        if topic:
            history = [h for h in history if h["topic"] == topic]
        return history[-limit:]
    
    # 兼容别名: life.py 调用 get_recent()
    def get_recent(self, limit: int = 50) -> list[dict]:
        """获取最近事件 (兼容别名)."""
        return self.get_history(limit=limit)
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            **self._stats,
            "topics": len(self._subscribers),
            "total_subscribers": sum(len(v) for v in self._subscribers.values()),
            "dead_letters": len(self._dead_letters),
            "history_size": len(self._history),
        }
