"""SkillDualLayerLoading — 技能双层加载系统

借鉴OpenOPC的Skill Dual-Layer Loading机制：
- Layer 1: 核心技能（常驻内存，快速访问）
- Layer 2: 扩展技能（按需加载，节省资源）
- 支持技能优先级、依赖管理和缓存策略
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """技能定义"""
    skill_id: str
    name: str
    description: str = ""
    priority: int = 5  # 1-10，越高越优先
    layer: int = 1  # 1=核心层，2=扩展层
    size_kb: float = 0.0  # 估算大小
    dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    loaded: bool = False
    last_accessed: float = 0.0
    access_count: int = 0

    def touch(self):
        """更新访问时间"""
        self.last_accessed = time.time()
        self.access_count += 1


class SkillDualLayerLoading:
    """技能双层加载系统

    核心层技能常驻内存，扩展层技能按需加载。
    支持LRU淘汰和依赖管理。
    """

    def __init__(self, core_layer_size_limit: float = 1024.0):
        """初始化

        Args:
            core_layer_size_limit: 核心层大小限制(KB)
        """
        self._core_layer_size_limit = core_layer_size_limit
        self._skills: dict[str, Skill] = {}
        self._loaded_skills: dict[str, Any] = {}  # skill_id -> skill_instance
        self._layer_index: dict[int, set[str]] = {1: set(), 2: set()}
        self._tag_index: dict[str, set[str]] = defaultdict(set)
        self._stats = {
            "total_skills": 0,
            "core_loaded": 0,
            "extension_loaded": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "evictions": 0,
        }

    def register_skill(self, skill: Skill) -> bool:
        """注册技能

        Args:
            skill: 技能对象

        Returns:
            是否成功
        """
        if skill.skill_id in self._skills:
            logger.warning("Skill %s already registered", skill.skill_id)
            return False

        self._skills[skill.skill_id] = skill
        self._layer_index[skill.layer].add(skill.skill_id)

        for tag in skill.tags:
            self._tag_index[tag].add(skill.skill_id)

        # 核心层技能自动加载
        if skill.layer == 1:
            self._load_skill(skill.skill_id)

        self._stats["total_skills"] += 1
        logger.info("Registered skill %s (layer=%d, priority=%d)",
                     skill.skill_id, skill.layer, skill.priority)
        return True

    def load_skill(self, skill_id: str) -> Any | None:
        """加载技能（按需）

        Args:
            skill_id: 技能ID

        Returns:
            技能实例或None
        """
        if skill_id not in self._skills:
            return None

        skill = self._skills[skill_id]

        # 如果已加载，直接返回
        if skill.loaded and skill_id in self._loaded_skills:
            self._stats["cache_hits"] += 1
            skill.touch()
            return self._loaded_skills[skill_id]

        # 检查依赖
        for dep_id in skill.dependencies:
            if dep_id not in self._skills or not self._skills[dep_id].loaded:
                logger.warning("Cannot load skill %s: missing dependency %s", skill_id, dep_id)
                return None

        # 加载技能
        self._load_skill(skill_id)
        self._stats["cache_misses"] += 1
        skill.touch()

        return self._loaded_skills.get(skill_id)

    def get_skill(self, skill_id: str) -> Any | None:
        """获取技能（自动加载）

        Args:
            skill_id: 技能ID

        Returns:
            技能实例或None
        """
        # 如果已加载，直接返回
        if skill_id in self._loaded_skills:
            self._stats["cache_hits"] += 1
            self._skills[skill_id].touch()
            return self._loaded_skills[skill_id]

        # 未加载则尝试加载
        return self.load_skill(skill_id)

    def find_skills_by_tag(self, tag: str, min_priority: int = 0) -> list[Skill]:
        """按标签查找技能

        Args:
            tag: 标签
            min_priority: 最低优先级

        Returns:
            技能列表
        """
        skill_ids = self._tag_index.get(tag, set())
        skills = []
        for sid in skill_ids:
            skill = self._skills.get(sid)
            if skill and skill.priority >= min_priority:
                skills.append(skill)
        return sorted(skills, key=lambda s: -s.priority)

    def find_skills_by_layer(self, layer: int) -> list[Skill]:
        """按层级查找技能

        Args:
            layer: 层级 (1=核心, 2=扩展)

        Returns:
            技能列表
        """
        skill_ids = self._layer_index.get(layer, set())
        skills = [self._skills[sid] for sid in skill_ids if sid in self._skills]
        return sorted(skills, key=lambda s: -s.priority)

    def evict_lru(self, max_extension_size: float = 512.0) -> int:
        """LRU淘汰扩展层技能

        Args:
            max_extension_size: 扩展层最大大小(KB)

        Returns:
            淘汰数量
        """
        evicted = 0

        # 计算当前扩展层大小
        current_size = sum(
            self._skills[sid].size_kb
            for sid in self._loaded_skills
            if self._skills.get(sid, {}).layer == 2
        )

        if current_size <= max_extension_size:
            return 0

        # 按最后访问时间排序（最旧的在前）
        extension_skills = [
            (sid, self._skills[sid])
            for sid in self._loaded_skills
            if self._skills.get(sid, {}).layer == 2
        ]
        extension_skills.sort(key=lambda x: x[1].last_accessed)

        # 淘汰直到满足大小限制
        for sid, skill in extension_skills:
            if current_size <= max_extension_size:
                break

            # 卸载技能
            self._unload_skill(sid)
            current_size -= skill.size_kb
            evicted += 1
            self._stats["evictions"] += 1

        logger.info("Evicted %d LRU skills from extension layer", evicted)
        return evicted

    def preload_high_priority(self, count: int = 10) -> int:
        """预加载高优先级技能

        Args:
            count: 预加载数量

        Returns:
            实际加载数量
        """
        # 获取未加载的高优先级技能
        unloaded = [
            (sid, skill)
            for sid, skill in self._skills.items()
            if not skill.loaded and skill.layer == 2
        ]
        unloaded.sort(key=lambda x: -x[1].priority)

        loaded = 0
        for sid, skill in unloaded[:count]:
            result = self.load_skill(sid)
            if result is not None:
                loaded += 1

        logger.info("Preloaded %d high-priority skills", loaded)
        return loaded

    def _load_skill(self, skill_id: str) -> bool:
        """内部加载方法"""
        if skill_id not in self._skills:
            return False

        skill = self._skills[skill_id]

        # 检查核心层大小限制
        if skill.layer == 1:
            current_size = sum(
                self._skills[s].size_kb
                for s in self._layer_index[1]
                if self._skills.get(s, {}).loaded
            )
            if current_size + skill.size_kb > self._core_layer_size_limit:
                # 需要淘汰低优先级的核心技能
                self._evict_low_priority_core()

        # 模拟加载（实际项目中这里会加载真正的技能模块）
        self._loaded_skills[skill_id] = {
            "skill_id": skill_id,
            "name": skill.name,
            "loaded_at": time.time(),
        }
        skill.loaded = True

        if skill.layer == 1:
            self._stats["core_loaded"] += 1
        else:
            self._stats["extension_loaded"] += 1

        return True

    def _unload_skill(self, skill_id: str) -> bool:
        """卸载技能"""
        if skill_id not in self._loaded_skills:
            return False

        del self._loaded_skills[skill_id]
        if skill_id in self._skills:
            self._skills[skill_id].loaded = False

        return True

    def _evict_low_priority_core(self) -> None:
        """淘汰低优先级核心技能"""
        core_skills = [
            (sid, self._skills[sid])
            for sid in self._layer_index[1]
            if self._skills.get(sid, {}).loaded
        ]
        core_skills.sort(key=lambda x: x[1].priority)  # 最低优先级在前

        # 淘汰最低优先级的技能
        for sid, skill in core_skills[:3]:
            self._unload_skill(sid)
            self._stats["evictions"] += 1

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "core_skills": len(self._layer_index[1]),
            "extension_skills": len(self._layer_index[2]),
            "cache_hit_rate": self._stats["cache_hits"] / max(self._stats["cache_hits"] + self._stats["cache_misses"], 1),
        }
