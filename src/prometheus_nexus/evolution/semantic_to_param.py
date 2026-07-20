"""SemanticToParam — T2 语义→参数映射器(Phase 3).

设计初衷(用户): T2 根据 learn 学到的内容, 语义促进系统强化.
即从 learn 节点的语义(反复出现的主题)映射到系统可调参数维度, 产出带置信度的
强化提案; 提案经 T1 进化引擎(inject_gene_specs + fitness 验证)做真闭环,
而非把概念名当无意义 (0,1) 占位直接写进 _gene_specs.

映射原则:
- 关键词 -> 系统真实可调维度(有语义, 非占位)
- 置信度 = min(1.0, 主题出现频次 / 阈值), 频次越高越确信应强化
- 搜索区间围绕当前值派生(与 T1 一致), 不接受则被 T1 fitness 否决
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


# 语义主题 -> 系统可调参数维度的有向映射(可扩展).
# 每个条目: 触发词(小写) -> (参数名, 默认值, 语义说明)
SEMANTIC_PARAM_MAP: dict[str, tuple[str, float]] = {
    "sparsity": ("attention_sparsity", 0.1),
    "sparse attention": ("attention_sparsity", 0.1),
    "稀疏": ("attention_sparsity", 0.1),
    "decay": ("memory_decay", 0.05),
    "遗忘": ("memory_decay", 0.05),
    "forgetting": ("memory_decay", 0.05),
    "temperature": ("llm_temperature", 0.7),
    "exploration": ("exploration_rate", 0.2),
    "explore": ("exploration_rate", 0.2),
    "consolidation": ("consolidation_strength", 0.3),
    "retention": ("retention_rate", 0.5),
    "plasticity": ("synaptic_plasticity", 0.4),
    "learning rate": ("learning_rate", 0.01),
    "utility": ("utility_threshold", 0.3),
    "dedup": ("dedup_threshold", 0.85),
    "threshold": ("activate_threshold", 0.3),
}


class SemanticToParam:
    """从 learn 语义聚类提取反复出现的主题, 映射为系统强化提案."""

    def __init__(self, param_map: dict[str, tuple[str, float]] | None = None,
                 freq_threshold: int = 3):
        self._map = param_map or SEMANTIC_PARAM_MAP
        self._freq_threshold = freq_threshold

    def derive_proposals(self, nodes: list[Any]) -> list[dict]:
        """从 learn 节点派生强化提案.

        Args:
            nodes: learn 已吸收的知识节点(含 tags/content/utility)

        Returns:
            list[dict]: [{param, default, lo, hi, confidence, theme, freq}, ...]
            仅含 freq >= 阈值 的主题(反复出现才值得强化).
        """
        theme_freq: dict[str, int] = defaultdict(int)
        theme_utility: dict[str, float] = defaultdict(float)
        for n in nodes:
            text = " ".join([
                " ".join(getattr(n, "tags", []) or []),
                (getattr(n, "content", "") or "")[:500],
            ]).lower()
            util = getattr(n, "utility", 0.0) or 0.0
            matched = set()
            for trigger in self._map:
                if trigger in text:
                    matched.add(trigger)
            for trig in matched:
                theme_freq[trig] += 1
                theme_utility[trig] = max(theme_utility[trig], util)

        proposals = []
        for trig, freq in theme_freq.items():
            if freq < self._freq_threshold:
                continue  # 偶发主题不强化(避免噪声)
            param, default = self._map[trig]
            confidence = min(1.0, freq / (self._freq_threshold * 2))
            lo = round(max(0.0, default * 0.5), 4)
            hi = round(max(default * 1.5, 0.01), 4)
            proposals.append({
                "param": param,
                "default": default,
                "lo": lo,
                "hi": hi,
                "confidence": confidence,
                "theme": trig,
                "freq": freq,
                "utility": round(theme_utility[trig], 3),
            })
        # 按置信度+频次降序, 高价值提案优先
        proposals.sort(key=lambda p: (p["confidence"], p["freq"]), reverse=True)
        return proposals

    def proposals_to_specs(self, proposals: list[dict]) -> dict[str, tuple[float, float]]:
        """把提案转成 gene_specs 格式(param:(lo,hi)), 供 T1 inject_gene_specs."""
        specs: dict[str, tuple[float, float]] = {}
        for p in proposals:
            specs[p["param"]] = (p["lo"], p["hi"])
        return specs
