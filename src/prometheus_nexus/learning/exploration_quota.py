"""ExplorationQuota — 探索配额管理.

基于:
- MiMo: "每日探索上限20轮,第10轮后必须插入修订轮"
  - 每日配额: 限制探索次数防止资源浪费
  - 修订轮插入: 强制反思点
  - 配额重置: 按日期自动重置
  - 使用跟踪: 记录配额使用情况

算法:
    can_explore():
        1. 检查日期是否变更(自动重置)
        2. 检查是否超过每日上限
        3. 检查是否触发修订轮
        4. 返回结果

复杂度:
    can_explore(): O(1), record_round(): O(1)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time


class ExplorationQuota:
    """探索配额管理器.
    
    每日限制 + 强制修订轮.
    """
    
    def __init__(self, max_daily: int = 99999999, revision_after: int = 10,
                 revision_count: int = 3, weekly_max: int = 99999999):
        """初始化.
        
        Args:
            max_daily: 每日最大探索数
            revision_after: 触发修订轮的次数
            revision_count: 修订轮次数
            weekly_max: 每周最大探索数
        """
        self._max_daily = max_daily
        self._revision_after = revision_after
        self._revision_count = revision_count
        self._weekly_max = weekly_max
        
        # 状态
        self._today_count = 0
        self._revisions_done = 0
        self._last_date = ""
        self._weekly_count = 0
        self._last_week = ""
        self._quota_history: list[dict] = []
    
    def _check_date(self):
        """检查日期变更,自动重置."""
        today = time.strftime('%Y-%m-%d')
        if today != self._last_date:
            self._quota_history.append({
                "date": self._last_date or "never",
                "count": self._today_count,
                "revisions": self._revisions_done,
            })
            self._today_count = 0
            self._revisions_done = 0
            self._last_date = today
        
        # 检查周重置
        week = time.strftime('%Y-W%W')
        if week != self._last_week:
            self._weekly_count = 0
            self._last_week = week
    
    def can_explore(self) -> tuple[bool, str]:
        """检查是否允许探索.
        
        Returns:
            tuple: (是否允许, 原因)
        """
        self._check_date()
        
        # 每日上限
        if self._today_count >= self._max_daily:
            remaining = (self._max_daily - self._today_count)
            return False, "daily_limit_reached (%d/%d)" % (self._today_count, self._max_daily)
        
        # 周上限
        if self._weekly_count >= self._weekly_max:
            return False, "weekly_limit_reached (%d/%d)" % (self._weekly_count, self._weekly_max)
        
        # 修订轮强制
        if self._today_count >= self._revision_after and self._revisions_done < self._revision_count:
            return True, "revision_round_required"
        
        return True, "ok"
    
    def record_round(self, is_revision: bool = False):
        """记录探索轮次.
        
        Args:
            is_revision: 是否为修订轮
        """
        self._check_date()
        
        self._today_count += 1
        self._weekly_count += 1
        
        if is_revision:
            self._revisions_done += 1
    
    def needs_revision(self) -> bool:
        """检查是否需要修订轮.
        
        Returns:
            bool: 是否需要修订
        """
        self._check_date()
        return (
            self._today_count >= self._revision_after and
            self._revisions_done < self._revision_count
        )
    
    def get_remaining(self) -> dict:
        """获取剩余配额.
        
        Returns:
            dict: 配额信息
        """
        self._check_date()
        
        return {
            "daily_remaining": self._max_daily - self._today_count,
            "daily_used": self._today_count,
            "weekly_remaining": self._weekly_max - self._weekly_count,
            "weekly_used": self._weekly_count,
            "revisions_done": self._revisions_done,
            "revisions_needed": self._revision_count,
        }
    
    def get_stats(self) -> dict:
        """获取统计."""
        remaining = self.get_remaining()
        
        return {
            "daily": {
                "used": self._today_count,
                "max": self._max_daily,
                "remaining": remaining["daily_remaining"],
            },
            "weekly": {
                "used": self._weekly_count,
                "max": self._weekly_max,
                "remaining": remaining["weekly_remaining"],
            },
            "revisions": {
                "done": self._revisions_done,
                "required": self._revision_count,
            },
            "history_days": len(self._quota_history),
        }
