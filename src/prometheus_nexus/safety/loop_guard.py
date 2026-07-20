"""LoopGuard — 循环保护.

基于:
- "Loop Detection with Pattern Analysis"
  - 迭代限制: 最大循环次数
  - 超时控制: 防止无限等待
  - 重复检测: 窗口内相同动作
  - 模式检测: 交替/周期模式识别

算法:
    check():
        1. 检查迭代次数
        2. 检查超时
        3. 检测重复模式
        4. 检测交替模式
        5. 返回状态

复杂度:
    check(): O(W) 其中W=检测窗口
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time


class LoopState:
    """循环状态枚举."""
    IDLE = "idle"
    RUNNING = "running"
    TIMEOUT = "timeout"
    MAX_ITERATIONS = "max_iterations"
    REPETITION = "repetition"
    PATTERN = "pattern"
    CIRCUIT_BREAKER = "circuit_breaker"


class LoopGuard:
    """循环保护器.
    
    多维度循环检测+熔断器.
    """
    
    def __init__(self, max_iterations: int = 100, timeout: float = 60.0,
                 repetition_window: int = 10, pattern_window: int = 20):
        """初始化.
        
        Args:
            max_iterations: 最大迭代次数
            timeout: 超时(秒)
            repetition_window: 重复检测窗口
            pattern_window: 模式检测窗口
        """
        self._max_iter = max_iterations
        self._timeout = timeout
        self._repetition_window = repetition_window
        self._pattern_window = pattern_window
        
        self._iterations = 0
        self._state = LoopState.IDLE
        self._start_time = 0.0
        self._history: list[str] = []
        self._break_count = 0
    
    def start(self):
        """开始监控."""
        self._iterations = 0
        self._state = LoopState.RUNNING
        self._start_time = time.time()
        self._history.clear()
    
    def record_action(self, action: str):
        """记录动作.
        
        Args:
            action: 动作标识
        """
        self._history.append(action)
        # 限制历史大小
        if len(self._history) > self._pattern_window * 2:
            self._history = self._history[-self._pattern_window * 2:]
    
    def check(self) -> str:
        """检查循��状态.
        
        Returns:
            str: 当前状态
        """
        self._iterations += 1
        
        # 1. 迭代次数检查
        if self._iterations >= self._max_iter:
            self._state = LoopState.CIRCUIT_BREAKER
            self._break_count += 1
            return self._state
        
        # 2. 超时检查
        if self._start_time > 0 and time.time() - self._start_time > self._timeout:
            self._state = LoopState.CIRCUIT_BREAKER
            self._break_count += 1
            return self._state
        
        # 3. 重复检测 (窗口内完全相同)
        if len(self._history) >= self._repetition_window:
            window = self._history[-self._repetition_window:]
            if len(set(window)) == 1:
                self._state = LoopState.CIRCUIT_BREAKER
                self._break_count += 1
                return self._state
        
        # 4. 交替模式检测 (ABABAB)
        if len(self._history) >= 6:
            last_6 = self._history[-6:]
            if (last_6[0] == last_6[2] == last_6[4] and
                last_6[1] == last_6[3] == last_6[5] and
                last_6[0] != last_6[1]):
                self._state = LoopState.CIRCUIT_BREAKER
                self._break_count += 1
                return self._state
        
        # 5. 周期模式检测 (ABCABC)
        if len(self._history) >= 9:
            last_9 = self._history[-9:]
            if (last_9[0] == last_9[3] == last_9[6] and
                last_9[1] == last_9[4] == last_9[7] and
                last_9[2] == last_9[5] == last_9[8] and
                len(set(last_9[:3])) > 1):
                self._state = LoopState.CIRCUIT_BREAKER
                self._break_count += 1
                return self._state
        
        self._state = LoopState.RUNNING
        return self._state
    
    def is_safe(self) -> bool:
        """是否安全.
        
        Returns:
            bool: 是否未触发熔断
        """
        return self._state == LoopState.RUNNING
    
    def reset(self):
        """重置."""
        self._iterations = 0
        self._state = LoopState.IDLE
        self._history.clear()
        self._start_time = 0
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "state": self._state,
            "iterations": self._iterations,
            "max_iterations": self._max_iter,
            "timeout_s": self._timeout,
            "history_size": len(self._history),
            "circuit_break_count": self._break_count,
            "is_safe": self.is_safe(),
        }
