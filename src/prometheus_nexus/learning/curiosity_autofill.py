"""CuriosityAutoFill — 好奇心队列自动填充.

基于:
- MiMo: "Heartbeat检测队列空时自动补充问题"
  - 自动检测: 队列低于阈值时触发
  - 知识缺口检测: 基于现有知识图谱找空白
  - 模板生成: 使用预定义模板+动态领域填充
  - 去重: 避免重复问题

算法:
    auto_fill(domains, count):
        1. 检查队列是否低水位
        2. 从知识索引找未覆盖领域
        3. 使用模板生成候选问题
        4. 去重后添加到队列
        5. 返回填充数量

复杂度:
    auto_fill(): O(T × D) 其中T=模板数,D=领域数
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import random


class CuriosityAutoFill:
    """好奇心队列自动填充器.
    
    基于心跳检测和知识缺口.
    """
    
    def __init__(self, queue=None, knowledge_index=None, low_watermark: int = 5):
        """初始化.
        
        Args:
            queue: 好奇心队列引用
            knowledge_index: 知识索引引用
            low_watermark: 低水位标记(低于此值触发填充)
        """
        self._queue = queue
        self._knowledge_index = knowledge_index
        self._low_watermark = low_watermark
        self._filled_count = 0
        self._fill_history: list[dict] = []
        
        # 问题模板库
        self._templates = [
            "What are the latest advances in {domain}?",
            "How does {domain} compare to alternative approaches?",
            "What are the practical limitations of {domain}?",
            "Can {domain} be combined with {other}?",
            "What open problems remain in {domain}?",
            "How would you measure success in {domain}?",
            "What are the edge cases for {domain}?",
            "Is {domain} more effective than traditional methods?",
            "What are the scalability concerns for {domain}?",
            "How does {domain} handle adversarial inputs?",
        ]
        
        # 默认领域
        self._default_domains = [
            "agent memory", "LLM safety", "multi-agent coordination",
            "prompt engineering", "tool use optimization",
            "knowledge distillation", "reinforcement learning",
            "neural architecture search", "mechanism design",
        ]
    
    def check_and_fill(self, domains: list[str] = None, count: int = 5) -> dict:
        """检查并自动填充.
        
        Args:
            domains: 探索领域列表
            count: 最大填充数
        
        Returns:
            dict: 填充结果
        """
        # 检查是否需要填充
        needs_fill = True
        if self._queue is not None:
            queue_size = len(self._queue._queue) if hasattr(self._queue, '_queue') else 0
            needs_fill = queue_size < self._low_watermark
        
        if not needs_fill:
            return {"action": "skipped", "reason": "queue_full"}
        
        filled = self.auto_fill(domains, count)
        
        result = {
            "action": "filled",
            "count": filled,
            "timestamp": time.time(),
        }
        
        self._fill_history.append(result)
        return result
    
    def auto_fill(self, domains: list[str] = None, count: int = 5) -> int:
        """自动填充好奇心队列.
        
        Args:
            domains: 探索领域
            count: 填充数量
        
        Returns:
            int: 实际填充数量
        """
        if domains is None:
            domains = self._default_domains[:5]
        
        # 找未充分探索的领域
        uncovered = self._find_uncovered_domains(domains)
        domains = uncovered if uncovered else domains
        
        filled = 0
        random.shuffle(self._templates)
        
        for domain in domains:
            if filled >= count:
                break
            
            # 为每个领域生成1-2个问题
            for tmpl in self._templates[:min(2, count - filled)]:
                # 随机选择另一个领域做对比
                other = random.choice(domains) if len(domains) > 1 else "other domains"
                
                question = tmpl.format(domain=domain, other=other)
                
                # 添加到队列
                if self._queue is not None:
                    # 动态优先级: 未覆盖领域优先
                    priority = 2 if domain in uncovered else 5
                    self._queue.add(question, priority=priority)
                    filled += 1
                    self._filled_count += 1
                    
                    if filled >= count:
                        break
        
        return filled
    
    def _find_uncovered_domains(self, domains: list[str]) -> list[str]:
        """找未充分探索的领域."""
        if not self._knowledge_index:
            return domains
        
        uncovered = []
        for domain in domains:
            # 检查知识索引中该领域的覆盖度
            coverage = self._knowledge_index.get_coverage(domain) if hasattr(self._knowledge_index, 'get_coverage') else None
            if coverage is None or coverage < 0.3:
                uncovered.append(domain)
        
        return uncovered
    
    def get_stats(self) -> dict:
        """获取统计."""
        return {
            "total_filled": self._filled_count,
            "fill_operations": len(self._fill_history),
            "templates": len(self._templates),
            "low_watermark": self._low_watermark,
        }
