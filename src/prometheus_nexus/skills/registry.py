"""SkillRegistry — 技能注册表.

基于:
- "Plugin Architecture with Versioning"
  - 技能注册: 名称+版本+标签
  - 版本管理: 递增版本号
  - 状态管理: active/inactive
  - 搜索: 按标签过滤

算法:
    register(skill):
        1. 提取技能元数据
        2. 生成/递增版本号
        3. 存储到注册表
    
    search(tags):
        1. 按标签过滤
        2. 返回匹配技能列表

复杂度:
    register(): O(1), search(): O(N) 其中N=技能数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time


class SkillRegistry:
    """技能注册表.
    
    支持版本管理和标签搜索.
    """
    
    def __init__(self):
        """初始化."""
        self._skills: list[dict] = []
        self._skill_map: dict[str, dict] = {}
        self._versions: dict[str, int] = {}
        self._invoke_history: list[dict] = []
        self.nexus = None  # 反向引用: Nexus 统一调用图(旁路记账)

    def register(self, skill=None, name: str = "", version: str = "",
                 tags: list[str] = None, description: str = "") -> dict:
        """注册技能.
        
        Args:
            skill: 技能对象(可选)
            name: 技能名称
            version: 版本号
            tags: 标签列表
            description: 描述
        
        Returns:
            dict: 注册结果
        """
        # 从对象提取元数据
        if skill is not None:
            name = name or getattr(skill, 'name', f'skill_{len(self._skills)}')
            tags = tags or getattr(skill, 'tags', [])
            description = description or getattr(skill, 'description', '')
        
        # 版本管理: 调用方显式传入 version 时予以尊重(修复前该参数被静默忽略,
        # 永远用自增 int 覆盖, 属幽灵参数); 未传入则自动递增。
        if version:
            current_version = version
        else:
            current_version = self._versions.get(name, 0) + 1
            self._versions[name] = current_version
        
        entry = {
            "name": name,
            "version": current_version,
            "registered_at": time.time(),
            "tags": tags or [],
            "description": description,
            "status": "active",
            "invoke_count": 0,
            "last_invoked": None,
        }
        
        # 重名再注册 = 发布新版本: 旧条目降级为 superseded, 保证每个 name
        # 全局仅一个 active 条目(修复前 _skill_map 只指向最新而 _skills 累积全部
        # 副本, 导致 get_active_skills/search 返回重复活跃条目, 违反不变量)。
        existing = self._skill_map.get(name)
        if existing is not None:
            existing["status"] = "superseded"
        self._skills.append(entry)
        self._skill_map[name] = entry
        
        return {
            "registered": True,
            "name": name,
            "version": current_version,
            "tags": tags,
        }
    
    def get_skill(self, name: str) -> dict | None:
        """获取技能.
        
        Args:
            name: 技能名称
        
        Returns:
            dict: 技能信息或None
        """
        return self._skill_map.get(name)
    
    def get_active_skills(self) -> list[dict]:
        """获取活跃技能.
        
        Returns:
            list: 活跃技能列表
        """
        return [s.copy() for s in self._skills if s["status"] == "active"]
    
    def search(self, tags: list[str]) -> list[dict]:
        """按标签搜索技能.
        
        Args:
            tags: 标签列表(OR匹配)
        
        Returns:
            list: 匹配的技能列表
        """
        if not tags:
            return self.get_active_skills()
        
        results = []
        for skill in self._skills:
            if skill["status"] != "active":
                continue
            skill_tags = set(skill.get("tags", []))
            search_tags = set(tags)
            if skill_tags & search_tags:  # 交集非空
                results.append(skill.copy())
        
        # 按匹配标签数排序
        results.sort(key=lambda s: len(set(s.get("tags", [])) & set(tags)), reverse=True)
        return results
    
    def activate(self, name: str) -> bool:
        """激活技能.
        
        Args:
            name: 技能名称
        
        Returns:
            bool: 是否成功
        """
        skill = self._skill_map.get(name)
        if not skill:
            return False
        
        skill["status"] = "active"
        skill["consumed_at"] = __import__("time").time()  # 方案Y: 技能激活=被宿主消费, 记时间戳供 B1 消费率观测
        if self.nexus is not None:
            self.nexus.mark_invoked(name)
        return True

    def deactivate(self, name: str) -> bool:
        """停用技能.
        
        Args:
            name: 技能名称
        
        Returns:
            bool: 是否成功
        """
        skill = self._skill_map.get(name)
        if not skill:
            return False
        
        skill["status"] = "inactive"
        return True
    
    def record_invoke(self, name: str, result: dict | None = None):
        """记录调用.

        Args:
            name: 技能名称
            result: 调用结果
        """
        skill = self._skill_map.get(name)
        if skill:
            skill["invoke_count"] += 1
            skill["last_invoked"] = time.time()
        if self.nexus is not None:
            self.nexus.mark_invoked(name)

        self._invoke_history.append({
            "name": name,
            "timestamp": time.time(),
            "result": result,
        })

    def get_stats(self) -> dict:

        """获取统计."""
        active = len([s for s in self._skills if s["status"] == "active"])
        inactive = len([s for s in self._skills if s["status"] == "inactive"])
        total_invokes = sum(s["invoke_count"] for s in self._skills)
        
        # 标签统计
        tag_counts = {}
        for s in self._skills:
            for tag in s.get("tags", []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        
        return {
            "total_skills": len(self._skills),
            "active": active,
            "inactive": inactive,
            "total_invocations": total_invokes,
            "invoke_history_size": len(self._invoke_history),
            "top_tags": dict(sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]),
        }
