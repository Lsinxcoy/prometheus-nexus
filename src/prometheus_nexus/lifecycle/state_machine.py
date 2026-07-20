"""状态机 — 生命周期管理

管道生命周期状态管理，支持状态转换验证、持久化恢复、超时重试。

状态流转:
    IDLE → RUNNING
    RUNNING → PAUSED, COMPLETED, ERROR
    PAUSED → RUNNING, IDLE
    COMPLETED → IDLE
    ERROR → IDLE, RUNNING
    CIRCUIT_BREAKER → IDLE

增强功能:
  - 状态持久化与恢复（JSON 文件）
  - 超时检测（状态停留超限时触发回调）
  - 重试机制（ERROR 状态自动重试）
  - 回调钩子（on_enter / on_exit）

基于 Omega 旧版 LoopStateMachine 重构增强。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from prometheus_nexus.foundation.schema import LoopState


# 合法状态转换矩阵
VALID_TRANSITIONS: Dict[LoopState, List[LoopState]] = {
    LoopState.IDLE: [LoopState.RUNNING],
    LoopState.RUNNING: [LoopState.PAUSED, LoopState.COMPLETED, LoopState.ERROR],
    LoopState.PAUSED: [LoopState.RUNNING, LoopState.IDLE],
    LoopState.COMPLETED: [LoopState.IDLE],
    LoopState.ERROR: [LoopState.IDLE, LoopState.RUNNING],
    LoopState.CIRCUIT_BREAKER: [LoopState.IDLE],
}


@dataclass
class TransitionRecord:
    """状态转换记录"""
    from_state: str
    to_state: str
    timestamp: float
    allowed: bool
    reason: Optional[str] = None


class LoopStateMachine:
    """管道生命周期状态机

    管理管道的完整生命周期，支持状态转换验证、回调钩子、
    持久化恢复、超时检测与自动重试。

    使用示例:
        sm = LoopStateMachine()
        sm.on_enter(LoopState.RUNNING, lambda: print("started"))
        sm.transition(LoopState.RUNNING)
        sm.save_state("pipe_state.json")
        # ... 重启后 ...
        sm.load_state("pipe_state.json")
    """

    def __init__(
        self,
        timeout_seconds: Optional[float] = None,
        max_retries: int = 0,
        on_timeout: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Args:
            timeout_seconds: 状态超时阈值（秒），超过后触发超时回调
            max_retries: ERROR 状态自动重试次数
            on_timeout: 超时回调函数 (state_name) -> None
        """
        self._state = LoopState.IDLE
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._on_timeout = on_timeout

        self._history: List[TransitionRecord] = []
        self._transition_counts: Dict[str, int] = {}
        self._on_enter: Dict[LoopState, Callable[..., Any]] = {}
        self._on_exit: Dict[LoopState, Callable[..., Any]] = {}

        self._state_entered_at: float = time.time()
        self._retry_count: int = 0

    @property
    def state(self) -> LoopState:
        """当前状态"""
        return self._state

    # ---------------------------------------------------------------
    # 状态转换
    # ---------------------------------------------------------------

    def transition(self, new_state: LoopState, reason: Optional[str] = None) -> bool:
        """执行状态转换（带验证）

        仅当目标状态在当前状态的合法转换列表中时才执行。

        Args:
            new_state: 目标状态
            reason: 转换原因说明（可选）

        Returns:
            转换是否成功
        """
        valid = VALID_TRANSITIONS.get(self._state, [])
        allowed = new_state in valid

        # 记录转换
        record = TransitionRecord(
            from_state=self._state.value,
            to_state=new_state.value,
            timestamp=time.time(),
            allowed=allowed,
            reason=reason,
        )
        self._history.append(record)

        key = f"{self._state.value}->{new_state.value}"
        self._transition_counts[key] = self._transition_counts.get(key, 0) + 1

        if allowed:
            # 执行退出回调
            old_state = self._state
            if old_state in self._on_exit:
                self._on_exit[old_state]()

            self._state = new_state
            self._state_entered_at = time.time()

            # ERROR → RUNNING 的重试计数
            if old_state == LoopState.ERROR and new_state == LoopState.RUNNING:
                self._retry_count += 1

            # 执行进入回调
            if new_state in self._on_enter:
                self._on_enter[new_state]()

        return allowed

    def force_transition(self, new_state: LoopState) -> None:
        """强制状态转换（跳过验证）

        用于异常恢复或紧急场景。

        Args:
            new_state: 目标状态
        """
        record = TransitionRecord(
            from_state=self._state.value,
            to_state=new_state.value,
            timestamp=time.time(),
            allowed=True,
            reason="forced",
        )
        self._history.append(record)
        self._state = new_state
        self._state_entered_at = time.time()

    # ---------------------------------------------------------------
    # 回调钩子
    # ---------------------------------------------------------------

    def on_enter(self, state: LoopState, fn: Callable[..., Any]) -> None:
        """注册进入某状态时的回调

        Args:
            state: 目标状态
            fn: 回调函数
        """
        self._on_enter[state] = fn

    def on_exit(self, state: LoopState, fn: Callable[..., Any]) -> None:
        """注册退出某状态时的回调

        Args:
            state: 源状态
            fn: 回调函数
        """
        self._on_exit[state] = fn

    # ---------------------------------------------------------------
    # 超时检测
    # ---------------------------------------------------------------

    def check_timeout(self) -> Optional[str]:
        """检查当前状态是否超时

        Returns:
            如果超时返回状态名，否则返回 None
        """
        if self._timeout_seconds is None:
            return None

        elapsed = time.time() - self._state_entered_at
        if elapsed > self._timeout_seconds:
            state_name = self._state.value
            if self._on_timeout:
                self._on_timeout(state_name)
            return state_name
        return None

    def remaining_time(self) -> Optional[float]:
        """当前状态剩余超时时间

        Returns:
            剩余秒数，如果未设置超时则返回 None
        """
        if self._timeout_seconds is None:
            return None
        elapsed = time.time() - self._state_entered_at
        return max(0.0, self._timeout_seconds - elapsed)

    # ---------------------------------------------------------------
    # 自动重试
    # ---------------------------------------------------------------

    def auto_retry(self) -> bool:
        """ERROR 状态下的自动重试

        如果未达到最大重试次数，自动转换回 RUNNING。

        Returns:
            是否执行了重试
        """
        if self._state != LoopState.ERROR:
            return False
        if self._retry_count >= self._max_retries:
            return False

        return self.transition(LoopState.RUNNING, reason=f"auto_retry #{self._retry_count + 1}")

    # ---------------------------------------------------------------
    # 状态持久化
    # ---------------------------------------------------------------

    def save_state(self, path: str) -> Dict[str, Any]:
        """将状态机完整状态保存到 JSON 文件

        包含: 当前状态、转换历史、计数、超时配置。

        Args:
            path: 保存路径

        Returns:
            保存的数据字典
        """
        data = {
            "version": 1,
            "timestamp": time.time(),
            "state": self._state.value,
            "state_entered_at": self._state_entered_at,
            "retry_count": self._retry_count,
            "max_retries": self._max_retries,
            "timeout_seconds": self._timeout_seconds,
            "transition_counts": self._transition_counts,
            "history": [
                {
                    "from": r.from_state,
                    "to": r.to_state,
                    "timestamp": r.timestamp,
                    "allowed": r.allowed,
                    "reason": r.reason,
                }
                for r in self._history
            ],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return data

    def load_state(self, path: str) -> bool:
        """从 JSON 文件恢复状态机

        Args:
            path: checkpoint 文件路径

        Returns:
            是否恢复成功
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return False

        self._state = LoopState(data["state"])
        self._state_entered_at = data.get("state_entered_at", time.time())
        self._retry_count = data.get("retry_count", 0)
        self._max_retries = data.get("max_retries", self._max_retries)
        self._timeout_seconds = data.get("timeout_seconds", self._timeout_seconds)
        self._transition_counts = data.get("transition_counts", {})

        self._history = [
            TransitionRecord(
                from_state=r["from"],
                to_state=r["to"],
                timestamp=r["timestamp"],
                allowed=r.get("allowed", True),
                reason=r.get("reason"),
            )
            for r in data.get("history", [])
        ]

        return True

    # ---------------------------------------------------------------
    # 查询
    # ---------------------------------------------------------------

    def get_valid_next(self) -> list[str]:
        """获取当前状态的合法下一状态列表

        Returns:
            合法状态名列表
        """
        return [s.value for s in VALID_TRANSITIONS.get(self._state, [])]

    def get_transition_history(self) -> list[dict]:
        """获取完整转换历史

        Returns:
            转换记录列表
        """
        return [
            {
                "from": r.from_state,
                "to": r.to_state,
                "timestamp": r.timestamp,
                "allowed": r.allowed,
                "reason": r.reason,
            }
            for r in self._history
        ]

    def get_stats(self) -> dict:
        """状态机统计信息

        Returns:
            包含当前状态、转换次数��超时信息等
        """
        invalid = sum(1 for r in self._history if not r.allowed)
        return {
            "state": self._state.value,
            "transitions": len(self._history),
            "transition_counts": dict(self._transition_counts),
            "invalid_transitions": invalid,
            "retry_count": self._retry_count,
            "max_retries": self._max_retries,
            "timeout_seconds": self._timeout_seconds,
            "remaining_time": self.remaining_time(),
            "valid_next": self.get_valid_next(),
        }

    def reset(self) -> None:
        """重置状态机到初始状态"""
        self._state = LoopState.IDLE
        self._state_entered_at = time.time()
        self._retry_count = 0
        self._history.clear()
        self._transition_counts.clear()
