"""SkillClaw — 技能抓取与发现.

基于:
- "Content-Based Retrieval for Skill Discovery"
  - 技能搜索: 关键词/标签匹配
  - 评分排序: 相关性+使用频率+评分
  - 缓存机制: 搜索结果缓存
  - 去重合并: 合并相似技能

算法:
    search(query, skills):
        1. 计算查询与技能的文本相似度
        2. 标签匹配加权
        3. 综合评分排序
        4. 返回Top-K结果

复杂度:
    search(): O(N) N=技能数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import math
from collections import Counter, defaultdict


class SkillClaw:
    """技能抓取器 — 基于内容检索发现匹配技能.
    
    搜索和排序技能库中的技能,返回最相关的匹配.
    """
    
    def __init__(self, max_results: int = 10):
        """初始化.
        
        Args:
            max_results: 最大结果数
        """
        self._max_results = max_results
        self._skills: dict[str, dict] = {}
        self._search_cache: dict[str, list] = {}
        self._search_log: list[dict] = []
    
    def register_skill(self, skill_id: str, name: str, description: str,
                       tags: list[str] | None = None, score: float = 1.0,
                       body: str = "", composes: list[str] | None = None) -> dict:
        """注册技能.

        Args:
            skill_id: 技能ID
            name: 技能名称
            description: 描述
            tags: 标签列表
            score: 基础评分
            body: 技能可执行体 (供 Proposer 组合复用, Phase A)
            composes: 依赖的子技能 ID 列表 (组合式技能合成, 借鉴 Agentic Proposing)

        Returns:
            dict: 技能信息
        """
        skill = {
            "id": skill_id,
            "name": name,
            "description": description,
            "tags": set(tags or []),
            "score": score,
            "usage_count": 0,
            "registered_at": time.time(),
            "body": body or "",
            "composes": list(composes or []),
            "text": f"{name} {description} {' '.join(tags or [])}".lower(),
        }

        self._skills[skill_id] = skill
        return skill

    def compose(self, goal: str, max_depth: int = 3) -> list[dict]:
        """组合式技能合成 (借鉴 Agentic Proposing): 给定目标, 选+组合子技能成 workflow.

        返回有序技能链 [skill_dict, ...], 每个含 resolved 的 body 与依赖。
        无 LLM 时退化为基础相关性排序; 有 LLM 时用 Proposer 做目标驱动选择。
        """
        candidates = self.search(goal, k=max(8, self._max_results))
        # 拓扑展开 composes 依赖 (至多 max_depth 层)
        chain: list[dict] = []
        seen: set[str] = set()

        def expand(sid: str, depth: int):
            if sid in seen or depth > max_depth:
                return
            sk = self._skills.get(sid)
            if not sk:
                return
            seen.add(sid)
            for dep in sk.get("composes", []):
                expand(dep, depth + 1)
            chain.append(sk)

        for c in candidates:
            expand(c["id"], 0)
        return chain

    def search(self, query: str, k: int | None = None) -> list[dict]:
        """搜索技能.
        
        Args:
            query: 查询字符串
            k: 返回数量
        
        Returns:
            list: 搜索结果
        """
        limit = k or self._max_results
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        # 检查缓存
        cache_key = f"{query_lower}:{limit}"
        if cache_key in self._search_cache:
            cached = self._search_cache[cache_key]
            # cached is a list; _cache_ts is appended as last element
            cache_ts = cached[-1].get("_cache_ts", 0) if cached and isinstance(cached[-1], dict) else 0
            if time.time() - cache_ts < 60:
                return [s for s in cached if isinstance(s, dict) and "_cache_ts" not in s]
        
        scored = []
        
        for skill_id, skill in self._skills.items():
            text = skill["text"]
            text_words = set(text.split())
            
            # 1. 文本相似度(Jaccard)
            if query_words and text_words:
                word_overlap = len(query_words & text_words)
                text_similarity = word_overlap / max(len(query_words | text_words), 1)
            else:
                text_similarity = 0.0
            
            # 2. 子串匹配
            substring_score = 0.0
            for word in query_words:
                if word in text and len(word) > 2:
                    substring_score += 0.3
            
            # 3. 标签匹配
            tag_overlap = len(query_words & skill["tags"])
            tag_score = min(tag_overlap * 0.2, 0.6)
            
            # 4. 使用频率加成
            frequency_bonus = min(skill["usage_count"] * 0.01, 0.2)
            
            # 综合得分
            combined = (
                text_similarity * 0.4 +
                substring_score +
                tag_score +
                frequency_bonus +
                skill["score"] * 0.1
            )
            
            scored.append({
                "id": skill_id,
                "name": skill["name"],
                "description": skill["description"][:100],
                "tags": list(skill["tags"]),
                "score": round(combined, 4),
                "usage_count": skill["usage_count"],
            })
        
        # 排序
        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:limit]
        
        # 更新使用计数
        for result in results:
            if result["id"] in self._skills:
                self._skills[result["id"]]["usage_count"] += 1
        
        # 缓存
        cached = list(results)
        cached.append({"_cache_ts": time.time()})
        self._search_cache[cache_key] = cached
        
        # 记���
        self._search_log.append({
            "query": query[:100],
            "results": len(results),
            "ts": time.time(),
        })
        if len(self._search_log) > 200:
            self._search_log = self._search_log[-100:]
        
        return results
    
    def get_skill(self, skill_id: str) -> dict | None:
        """获取技能详情.
        
        Args:
            skill_id: 技能ID
        
        Returns:
            dict | None: 技能信息
        """
        skill = self._skills.get(skill_id)
        if not skill:
            return None
        
        return {
            "id": skill["id"],
            "name": skill["name"],
            "description": skill["description"],
            "tags": list(skill["tags"]),
            "score": skill["score"],
            "usage_count": skill["usage_count"],
        }
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "total_skills": len(self._skills),
            "total_searches": len(self._search_log),
            "cache_size": len(self._search_cache),
        }
    
    # 兼容别名: life.py 调用 route(query)
    def route(self, query: str) -> list[dict]:
        """路由查询到匹配的技能 (兼容别名)."""
        return self.search(query)
