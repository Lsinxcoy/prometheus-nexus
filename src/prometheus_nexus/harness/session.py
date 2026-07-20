"""Session — 会话生命周期管理.

基于:
- "Session Management with LRU Eviction"
  - LRU淘汰: 最少使用的会话优先过期
  - 空闲超时: 自动清理空闲会话
  - 会话状态: active/idle/expired
  - 操作计数: 用于活跃度评估

算法:
    create(name):
        1. 创建会话记录
        2. 更新访问时间和操作计数
    
    expire_idle():
        1. 检查所有活跃会话
        2. 按空闲时间排序
        3. 淘汰超过超时的会话

复杂度:
    create/access(): O(1), expire_idle(): O(N)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
from collections import OrderedDict


class Session:
    """会话管理器.
    
    LRU淘汰 + 空闲超时.
    """
    
    def __init__(self, idle_timeout: float = 3600.0, max_sessions: int = 100):
        """初始化.
        
        Args:
            idle_timeout: 空闲超时(秒)
            max_sessions: 最大会话数
        """
        self._idle_timeout = idle_timeout
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, dict] = OrderedDict()
        self._all_history: list[dict] = []
        self._created_count = 0
    
    def create(self, name: str) -> dict:
        """创建会话.
        
        Args:
            name: 会话名称
        
        Returns:
            dict: 会话信息
        """
        now = time.time()
        
        # 检查是否存在
        if name in self._sessions:
            self._sessions[name]["state"] = "recreated"
        
        # LRU: 移到末尾(最新访问)
        if name in self._sessions:
            self._sessions.move_to_end(name)
        
        session = {
            "name": name,
            "created_at": now,
            "last_accessed": now,
            "state": "active",
            "operations": 0,
            "idle_time_s": 0,
        }
        
        self._sessions[name] = session
        self._created_count += 1
        self._all_history.append(session.copy())
        
        # 超过最大会话数,淘汰最旧的
        while len(self._sessions) > self._max_sessions:
            evicted_name, evicted = self._sessions.popitem(last=False)
            evicted["state"] = "evicted_lru"
            self._all_history.append(evicted)
        
        return session
    
    def access(self, name: str, operation: str = "") -> dict | None:
        """访问会话.
        
        Args:
            name: 会话名称
            operation: 操作名称
        
        Returns:
            dict: 会话信息或None
        """
        if name not in self._sessions:
            return None
        
        session = self._sessions[name]
        now = time.time()
        
        session["last_accessed"] = now
        session["operations"] += 1
        session["idle_time_s"] = 0
        session["last_operation"] = operation
        session["state"] = "active"
        
        # 移到末尾(LRU)
        self._sessions.move_to_end(name)
        
        return session
    
    def expire_idle(self) -> list[dict]:
        """淘汰空闲会话.
        
        Returns:
            list: 被淘汰的会话列表
        """
        now = time.time()
        expired = []
        
        # 复制items避免修改时迭代问题
        for name in list(self._sessions.keys()):
            session = self._sessions[name]
            idle_time = now - session["last_accessed"]
            session["idle_time_s"] = idle_time
            
            if idle_time > self._idle_timeout:
                session["state"] = "expired"
                del self._sessions[name]
                expired.append(session)
        
        return expired
    
    def get_session(self, name: str) -> dict | None:
        """获取会话.
        
        Args:
            name: 会话名称
        
        Returns:
            dict: 会话信息或None
        """
        if name not in self._sessions:
            return None
        
        session = self._sessions[name]
        now = time.time()
        session["idle_time_s"] = now - session["last_accessed"]
        
        return session.copy()
    
    def get_stats(self) -> dict:
        """获取统计."""
        states = {}
        for s in self._sessions.values():
            state = s["state"]
            states[state] = states.get(state, 0) + 1
        
        idle_times = [s["idle_time_s"] for s in self._sessions.values()]
        avg_idle = sum(idle_times) / max(len(idle_times), 1)
        
        total_ops = sum(s["operations"] for s in self._sessions.values())
        
        return {
            "total_sessions": len(self._all_history),
            "active_sessions": len(self._sessions),
            "created_total": self._created_count,
            "states": states,
            "avg_idle_time_s": round(avg_idle, 2),
            "total_operations": total_ops,
            "max_sessions": self._max_sessions,
        }
