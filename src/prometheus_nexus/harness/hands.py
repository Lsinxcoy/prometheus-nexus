"""Hands — 工具执行引擎.

基于:
- "Resilient Execution with Retry and Circuit Breaker"
  - 重试策略: 指数退避 + 最大尝试次数
  - 超时控制: 防止无限等待
  - 熔断器: 连续失败后暂停执行
  - 执行历史: 记录用于分析和调试

算法:
    execute(action, executor):
        1. 检查熔断器状态
        2. 设置超时
        3. 循环重试(指数退避)
        4. 更新熔断器状态
        5. 记录执行历史

复杂度:
    execute(): O(R) 其中R=最大重试次数
"""
from __future__ import annotations
import time
import logging

logger = logging.getLogger(__name__)

import math
from collections import deque


class Hands:
    """执行引擎.
    
    支持重试、超时、熔断器.
    """
    
    def __init__(self, max_retries: int = 3, timeout: float = 30.0,
                 circuit_breaker_threshold: int = 5, circuit_breaker_timeout: float = 60.0):
        """初始化.
        
        Args:
            max_retries: 最大重试次数
            timeout: 超时(秒)
            circuit_breaker_threshold: 熔断器触发阈值(连续失败次数)
            circuit_breaker_timeout: 熔断器冷却时间(秒)
        """
        self._max_retries = max_retries
        self._timeout = timeout
        self._executions: list[dict] = []
        self._success_count = 0
        self._failure_count = 0
        self._total_latency_ms = 0.0
        
        # 熔断器状态
        self._cb_threshold = circuit_breaker_threshold
        self._cb_timeout = circuit_breaker_timeout
        self._consecutive_failures = 0
        self._cb_opened_at: float | None = None
    
    @property
    def is_circuit_open(self) -> bool:
        """检查熔断器是否打开."""
        if self._cb_opened_at is None:
            return False
        if time.time() - self._cb_opened_at > self._cb_timeout:
            # 超时后重置(半开状态)
            self._cb_opened_at = None
            self._consecutive_failures = 0
            return False
        return True
    
    def execute(self, action: dict | None = None, executor=None) -> dict:
        """执行动作.
        
        Args:
            action: 动作配置
            executor: 执行函数(可选)
        
        Returns:
            dict: 执行结果
        """
        action = action or {}
        
        # 检查熔断器
        if self.is_circuit_open:
            return {
                "executed": False,
                "error": "circuit_breaker_open",
                "retry_after_s": self._cb_timeout - (time.time() - (self._cb_opened_at or 0)),
            }
        
        start = time.time()
        last_error = None
        
        for attempt in range(self._max_retries):
            # 超时检查
            elapsed = time.time() - start
            if elapsed > self._timeout:
                last_error = "timeout"
                break
            
            # 指数退避(首次不等待)
            if attempt > 0:
                delay = min(0.1 * (2 ** (attempt - 1)), 5.0)
                time.sleep(delay)
            
            try:
                result = executor(action) if executor else self._default_execute(action)
                elapsed_ms = (time.time() - start) * 1000
                
                # 成功: 重置熔断器
                self._consecutive_failures = 0
                self._cb_opened_at = None
                
                execution = {
                    "executed": True,
                    "result": result,
                    "attempts": attempt + 1,
                    "elapsed_ms": elapsed_ms,
                    "action_type": action.get("action", "unknown"),
                }
                self._executions.append(execution)
                self._success_count += 1
                self._total_latency_ms += elapsed_ms
                return execution
            
            except Exception as e:
                last_error = str(e)
        
        # 所有重试失败
        elapsed_ms = (time.time() - start) * 1000
        self._consecutive_failures += 1
        
        # 检查是否触发熔断器
        if self._consecutive_failures >= self._cb_threshold:
            self._cb_opened_at = time.time()
        
        execution = {
            "executed": False,
            "error": last_error or "execution_failed",
            "attempts": self._max_retries,
            "elapsed_ms": elapsed_ms,
            "consecutive_failures": self._consecutive_failures,
            "circuit_breaker_open": self.is_circuit_open,
        }
        self._executions.append(execution)
        self._failure_count += 1
        self._total_latency_ms += elapsed_ms
        return execution
    
    def _default_execute(self, action: dict) -> dict:
        """默认执行器."""
        return {
            "status": "completed",
            "action_type": action.get("action", "unknown"),
            "timestamp": time.time(),
        }
    
    def get_stats(self) -> dict:
        """获取统计."""
        total = self._success_count + self._failure_count
        recent = self._executions[-20:] if self._executions else []
        recent_success = sum(1 for e in recent if e.get("executed"))
        
        return {
            "executions": len(self._executions),
            "successes": self._success_count,
            "failures": self._failure_count,
            "success_rate": round(self._success_count / max(total, 1), 3),
            "avg_latency_ms": round(self._total_latency_ms / max(len(self._executions), 1), 2),
            "recent_success_rate": round(recent_success / max(len(recent), 1), 3),
            "circuit_breaker_open": self.is_circuit_open,
            "consecutive_failures": self._consecutive_failures,
        }
