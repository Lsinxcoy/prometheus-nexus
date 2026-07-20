"""BrainstormingPrompt — 头脑风暴提示生成器.

基于:
- "Brainstorming: State of the Art and Promotion of Rigor" (Paulo & Nijkamp, 2015)
  - 延迟判断: 不急于评价想法
  - 数量优先: 越多想法越好
  - 组合改进: 想法组合产生新想法
  - 自由联想: 无限制创意

算法:
    generate(topic, count):
        1. 解析主题
        2. 提取关键词
        3. 多角度联想
        4. 组合生成
        5. 评分排序

复杂度:
    generate(): O(C log C) 其中 C = 生成想法数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import random
import time
import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Idea:
    """创意想法."""
    content: str = ""
    category: str = ""
    novelty: float = 0.0
    feasibility: float = 0.0
    connections: list[str] = field(default_factory=list)
    id: str = ""
    
    @property
    def score(self) -> float:
        return 0.6 * self.novelty + 0.4 * self.feasibility


class BrainstormingPrompt:
    """头脑风暴提示生成器.
    
    多角度创���生成器.
    """
    
    # 创意角度
    PERSPECTIVES = [
        "technical", "business", "user_experience", "scientific",
        "creative", "practical", "theoretical", "experimental",
        "incremental", "radical", "minimal", "maximal",
    ]
    
    def __init__(self, min_count: int = 5, max_count: int = 20):
        self.min_count = min_count
        self.max_count = max_count
        self._history: list[dict] = []
        self._idea_bank: list[str] = []
    
    def generate(self, topic: str, count: int | None = None, perspective: str = "") -> list[Idea]:
        """生成创意想法."""
        start = time.time()
        num = count or random.randint(self.min_count, self.max_count)
        
        if perspective:
            perspectives = [perspective]
        else:
            perspectives = random.sample(self.PERSPECTIVES, min(4, len(self.PERSPECTIVES)))
        
        # 提取主题关键词
        keywords = self._extract_keywords(topic)
        
        ideas: list[Idea] = []
        
        for p in perspectives:
            for i in range(num // len(perspectives)):
                idea = self._generate_idea(topic, keywords, p, i)
                ideas.append(idea)
        
        # 想法组合（交叉 pollination）
        if len(ideas) >= 4:
            combined = self._combine_ideas(ideas)
            ideas.extend(combined)
        
        # 按分数排序
        ideas.sort(key=lambda x: x.score, reverse=True)
        
        # 记录历史
        self._history.append({
            "topic": topic,
            "perspectives": perspectives,
            "count": len(ideas),
            "avg_score": sum(i.score for i in ideas) / len(ideas) if ideas else 0,
            "duration_ms": (time.time() - start) * 1000,
        })
        
        return ideas[:num]
    
    def _extract_keywords(self, topic: str) -> list[str]:
        """提取关键词."""
        words = topic.lower().split()
        # 移除常见停用词
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "of", "in", "on", "at", "to", "for"}
        return [w for w in words if w not in stop_words and len(w) > 2]
    
    def _generate_idea(self, topic: str, keywords: list[str], perspective: str, index: int) -> Idea:
        """从特定角度生成想法."""
        # 基于关键词和角度构建想法
        template_prefixes = {
            "technical": ["利用{kw}技术", "通过{kw}实现", "{kw}驱动的"],
            "business": ["{kw}商业模式", "{kw}市场机会", "{kw}变现方案"],
            "user_experience": ["用户导向的{kw}", "{kw}交互设计", "{kw}用户体验"],
            "scientific": ["{kw}的科学原理", "{kw}研究假设", "{kw}实验设计"],
            "creative": ["创意{kw}概念", "{kw}艺术表达", "{kw}创新设计"],
            "practical": ["实用的{kw}方案", "{kw}实施步骤", "{kw}最佳实践"],
            "theoretical": ["{kw}理论框架", "{kw}数学模型", "{kw}形式化定义"],
            "experimental": ["{kw}原型实验", "{kw}A/B测试", "{kw}探索性研究"],
        }
        
        prefix_list = template_prefixes.get(perspective, ["关于{kw}的想法"])
        prefix = random.choice(prefix_list)
        
        if keywords:
            kw = random.choice(keywords)
            content = prefix.format(kw=kw)
        else:
            content = f"{perspective}角度: {topic}"
        
        # 计算新颖性和可行性
        novelty = random.uniform(0.3, 0.95)
        feasibility = random.uniform(0.3, 0.95)
        
        idea = Idea(
            content=content,
            category=perspective,
            novelty=novelty,
            feasibility=feasibility,
            id=hashlib.md5(f"{content}_{index}".encode()).hexdigest()[:8],
        )
        
        # 添加到想法库
        self._idea_bank.append(content)
        
        return idea
    
    def _combine_ideas(self, ideas: list[Idea]) -> list[Idea]:
        """组合想法产生新想法."""
        combined = []
        sample = random.sample(ideas, min(4, len(ideas)))
        
        for i in range(len(sample)):
            for j in range(i + 1, len(sample)):
                a, b = sample[i], sample[j]
                new_content = f"结合'{a.content}'与'{b.content}'"
                combined.append(Idea(
                    content=new_content,
                    category=f"{a.category}+{b.category}",
                    novelty=max(a.novelty, b.novelty) * 1.1,
                    feasibility=min(a.feasibility, b.feasibility) * 0.9,
                    connections=[a.id, b.id],
                    id=hashlib.md5(new_content.encode()).hexdigest()[:8],
                ))
        
        return combined[:3]  # 最多3个组合想法
    
    def get_stats(self) -> dict:
        """获取统计."""
        total_ideas = sum(h["count"] for h in self._history)
        return {
            "sessions": len(self._history),
            "total_ideas": total_ideas,
            "avg_per_session": total_ideas / max(len(self._history), 1),
            "avg_score": (sum(h["avg_score"] for h in self._history) / len(self._history)) if self._history else 0,
            "idea_bank_size": len(self._idea_bank),
        }

    def brainstorm(self, problem: str, num_ideas: int = 5) -> list[dict]:
        """生成创意想法（兼容API）。"""
        ideas = []
        # 提取关键词
        keywords = self._extract_keywords(problem)
        # 随机选择角度
        perspectives = random.sample(self.PERSPECTIVES, min(4, len(self.PERSPECTIVES)))
        
        for i in range(num_ideas):
            perspective = perspectives[i % len(perspectives)]
            idea = self._generate_idea(problem, keywords, perspective, i)
            ideas.append({
                "content": idea.content,
                "category": idea.category,
                "novelty": idea.novelty,
                "feasibility": idea.feasibility,
                "id": idea.id,
            })
        return ideas
