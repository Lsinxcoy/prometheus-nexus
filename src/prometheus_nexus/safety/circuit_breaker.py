"""CircuitBreaker — 熔断器保护.

基于:
- "Circuit Breaker Pattern" (N. Fogh, 2008)
  - 三种状态: closed(正常)/open(熔断)/half-open(探测)
  - 失败计数: 连续失败超过阈值→熔断
  - 恢复探测: 半开状态单次尝试
  - 自动复位: 成功探测后恢复

算法:
    call(func, *args):
        1. 检查当前状态
        2. closed→执行并记录结果
        3. open→直接拒绝(超时后转half-open)
        4. half-open→单次探测

复杂度:
    call(): O(1)
"""
from __future__ import annotations
import time
import logging

logger = logging.getLogger(__name__)

from enum import Enum


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """熔断器 — 保护下游服务不被连续失败压垮.
    
    连续失败达到阈值后自动熔断,冷却期后尝试恢复.
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0,
                 half_open_max_calls: int = 1):
        """初始化.
        
        Args:
            failure_threshold: 失败阈值
            recovery_timeout: 熔断后等待恢复的秒数
            half_open_max_calls: 半开状态允许的最大调用数
        """
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls
        
        self._state = State.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        self._total_calls = 0
        self._total_failures = 0
        self._state_changes: list[dict] = []
    
    def call(self, func, *args, **kwargs):
        """执行函数调用(带熔断保护).
        
        Args:
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
        
        Returns:
            函数返回值
        
        Raises:
            Exception: 熔断状态或函数异常
        """
        self._total_calls += 1
        
        if self._state == State.OPEN:
            # 检查是否过了恢复时间
            if time.time() - self._last_failure_time >= self._recovery_timeout:
                self._change_state(State.HALF_OPEN)
                self._half_open_calls = 0
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit is open. Retry after {self._recovery_timeout}s"
                )
        
        if self._state == State.HALF_OPEN:
            if self._half_open_calls >= self._half_open_max_calls:
                raise CircuitBreakerOpenError(
                    "Half-open limit reached, re-opening circuit"
                )
            self._half_open_calls += 1
        
        # 执行调用
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self) -> None:
        """成功回调."""
        self._success_count += 1
        self._failure_count = 0
        
        if self._state == State.HALF_OPEN:
            self._change_state(State.CLOSED)
    
    def _on_failure(self) -> None:
        """失败回调."""
        self._failure_count += 1
        self._total_failures += 1
        self._last_failure_time = time.time()
        
        if self._state == State.HALF_OPEN:
            self._change_state(State.OPEN)
        elif self._failure_count >= self._failure_threshold:
            self._change_state(State.OPEN)
    
    def _change_state(self, new_state: State) -> None:
        """改变状态.
        
        Args:
            new_state: 新状态
        """
        old_state = self._state
        self._state = new_state
        
        if old_state != new_state:
            self._state_changes.append({
                "from": old_state.value,
                "to": new_state.value,
                "ts": time.time(),
            })
            if len(self._state_changes) > 100:
                self._state_changes = self._state_changes[-50:]
    
    def is_closed(self) -> bool:
        """是否闭合（正常状态）."""
        return self._state == State.CLOSED
    
    # 兼容别名: life.py 调用 record_success() / record_failure()
    def record_success(self) -> None:
        """记录成功 (兼容别名)."""
        self._on_success()
    
    def record_failure(self) -> None:
        """记录失败 (兼容别名)."""
        self._on_failure()
    
    def allow_request(self) -> bool:
        """是否允许请求 (兼容别名)."""
        if self._state == State.CLOSED:
            return True
        if self._state == State.OPEN:
            if time.time() - self._last_failure_time >= self._recovery_timeout:
                self._change_state(State.HALF_OPEN)
                self._half_open_calls = 0
                return True
            return False
        # HALF_OPEN
        if self._half_open_calls < self._half_open_max_calls:
            self._half_open_calls += 1
            return True
        return False
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "state": self._state.value,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "failure_rate": round(
                self._total_failures / max(self._total_calls, 1), 4
            ),
            "failure_count": self._failure_count,
            "state_changes": len(self._state_changes),
        }
    
    def get_state(self) -> str:
        """获取当前状态 (兼容别名)."""
        return self._state.value


class CircuitBreakerOpenError(Exception):
    """熔断器打开异常."""
    pass
