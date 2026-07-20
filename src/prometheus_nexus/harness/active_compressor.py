"""ActiveCompressor — 主动上下文压缩器，集成 Focus Agent (arXiv 2601.07190) 黏菌启发式架构。

Focus Agent 论文描述了受黏菌 (slime mold / Physarum polycephalum) 探索行为启发的
主动上下文压缩架构。核心洞察：黏菌在资源丰富时扩张探索网络，在资源匮乏时收缩网络
并将营养集中在关键节点。对应地，LLM 上下文管理器应:

1. Saw-Tooth 检测：监测 token 使用量的"锯齿模式"(build-up → compress → build-up)
2. Slime Mold 探索：自主决定何时扩张（保留更多上下文）或收缩（压缩关键词）
3. Focus 压缩：不简单删除旧内容，而是提取关键学习内容（summarize, don't truncate）

当前实现:
- ActiveCompressor — 原有基于阈值的触发压缩器（保留）
- SawToothDetector — 检测 token 使用量的锯齿模式
- SlimeMoldExplorer — 基于信息密度自主决定扩张/收缩
- FocusCompressor — 提取关键学习内容的语义压缩器（替代简单删除）
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 25000
_DEFAULT_COMPRESSION_RATIO = 0.3
_DEFAULT_SAW_TOOTH_THRESHOLD = 0.85

# Focus Agent 默认配置
_DEFAULT_INFO_DENSITY_THRESHOLD = 0.35       # 低于此 → 应该压缩
_DEFAULT_EXPLORE_THRESHOLD = 0.50             # 信息密度 > 此 → 继续探索 (保留上下文)
_DEFAULT_SAW_TOOTH_WINDOW = 5                  # 锯齿检测窗口大小
_DEFAULT_MIN_LEARNINGS_LENGTH = 20             # 提取的关键学习最短长度
_DEFAULT_ENTROPY_THRESHOLD = 3.5                # Shannon 熵低于此 → 低信息密度
_DEFAULT_MAX_LEARNINGS = 3                      # extract_key_learnings 默认返回条数


# ======================================================================
# extract_key_learnings — 模块级关键学习提取函数
# ======================================================================

def extract_key_learnings(text: str, max_items: int = _DEFAULT_MAX_LEARNINGS) -> list[str]:
    """从文本中提取关键学习点（模块级便利函数）。

    适用于无需创建 FocusCompressor 实例的场景。
    使用简单的启发式规则提取最重要的信息点。

    Args:
        text: 输入文本
        max_items: 最大返回条数（默认 3）

    Returns:
        关键学习点列表，按重要性降序排列
    """
    if not text or len(text) < _DEFAULT_MIN_LEARNINGS_LENGTH:
        return []

    lines = text.split("\n")
    scored: list[tuple[float, str]] = []

    # 定义关键词及权重（分数越高越重要）
    high_confidence = {
        "conclusion", "summary", "result", "found that", "therefore",
        "key insight", "important", "critical", "crucial",
        "learned", "discovered", "identified", "confirmed",
    }
    medium_confidence = {
        "decision", "chosen", "selected", "recommended",
        "solution", "workaround", "root cause",
        "increase", "decrease", "improvement", "decline",
    }
    indicator_patterns = [
        (r"\d+[%×]", 1.5),
        (r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", 0.5),
        (r"\d+[\.\d]*", 0.3),
    ]

    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 15:
            continue

        score = 0.0

        # 高置信度关键词
        lower = stripped.lower()
        for kw in high_confidence:
            if kw in lower:
                score += 3.0
        for kw in medium_confidence:
            if kw in lower:
                score += 1.5

        # 列表项
        if stripped.startswith(("- ", "* ", "• ", "→ ", "=> ", "✅ ", "❌ ")):
            score += 2.0
        if re.match(r"^\d+[\.\)]", stripped):
            score += 1.5

        # 模式匹配
        for pattern, weight in indicator_patterns:
            if re.search(pattern, stripped):
                score += weight

        # 长度奖励（不太短也不太长的句子最有价值）
        length = len(stripped)
        if 40 <= length <= 300:
            score += 1.0
        elif length > 300:
            score += 0.5

        if score > 0:
            scored.append((score, stripped.strip()))

    # 按分数降序排列
    scored.sort(key=lambda x: x[0], reverse=True)

    # 去重
    seen: set[str] = set()
    unique: list[str] = []
    for _, item in scored:
        norm = item.lower().strip()
        # 短 ngram 去重：如果前 30 个字符已存在则跳过
        prefix = norm[:30]
        if prefix not in seen:
            seen.add(prefix)
            unique.append(item)
            if len(unique) >= max_items:
                break

    return unique


# ======================================================================
# shannon_entropy — 信息论熵估算
# ======================================================================

def shannon_entropy(text: str) -> float:
    """计算一段文本的 Shannon 信息熵（保留 4 位小数）。

    熵越高 → 信息越丰富 / 多样性越高
    熵越低 → 文本越重复 / 可预测性越高

    Args:
        text: 输入文本

    Returns:
        Shannon 熵值（基于字符频率）。空文本返回 0.0。
    """
    if not text:
        return 0.0

    text_len = len(text)
    freq: dict[str, int] = {}
    for ch in text:
        freq[ch] = freq.get(ch, 0) + 1

    entropy = 0.0
    for count in freq.values():
        p = count / text_len
        if p > 0:
            entropy -= p * math.log2(p)

    return round(entropy, 4)


# ======================================================================
# estimate_information_density — 综合信息密度估算
# ======================================================================

def estimate_information_density(text: str) -> float:
    """估算文本的综合信息密度 (0.0 ~ 1.0)。

    结合 Shannon 熵、实体密度、动作密度和词汇独特性。

    Args:
        text: 输入文本

    Returns:
        0.0 (完全冗余) ~ 1.0 (极高信息密度)
    """
    if not text or len(text) < 5:
        return 0.0

    # 1. Shannon 熵分量（归一化到 0~1）
    ent = shannon_entropy(text)
    # 英文文本���型熵范围 ~4-6 bit/char, ASCII ≤ ~6.5
    ent_norm = min(1.0, ent / 6.5)

    # 2. 实体密度
    entities = len(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text))
    numbers = len(re.findall(r"\b\d+[\.\d]*\b", text))
    word_count = max(len(text.split()), 1)
    entity_density = (entities + numbers) / word_count

    # 3. 动作密度
    actions = len(re.findall(
        r"\b(?:run|exec|write|read|create|delete|update|"
        r"call|send|fetch|compute|analyze|transform|build|"
        r"deploy|compile|test|validate|search|find)\b",
        text, re.IGNORECASE,
    ))
    action_density = actions / word_count

    # 4. 词汇独特性
    words = text.lower().split()
    unique_ratio = len(set(words)) / len(words) if words else 1.0

    # 加权综合
    density = (
        ent_norm * 0.30
        + entity_density * 0.25
        + action_density * 0.25
        + unique_ratio * 0.20
    )

    return round(min(1.0, density * 2.5), 4)


# ======================================================================
# SawToothDetector — 检测 token 使用量的锯齿模式
# ======================================================================

class SawToothDetector:
    """检测 token 使用量的"锯齿模式"(build-up → compress → build-up)。

    Focus Agent 论文观察到，正常对话的 token 使用量呈现锯齿波：
    长时间上升（积累上下文）→ 快速下降（压缩）→ 再上升。
    如果检测不到这种模式，说明压缩策略可能需要调整。
    """

    def __init__(self, window_size: int = _DEFAULT_SAW_TOOTH_WINDOW):
        self._window_size = window_size
        self._token_history: deque[int] = deque(maxlen=window_size)
        self._timestamps: deque[float] = deque(maxlen=window_size)
        self._compress_events: list[dict] = []

    def record(self, token_count: int) -> None:
        """记录一个时间点的 token 使用量。"""
        self._token_history.append(token_count)
        self._timestamps.append(time.time())

    def record_compress(self, before: int, after: int, method: str = "threshold") -> None:
        """记录一次压缩事件。"""
        self._compress_events.append({
            "timestamp": time.time(),
            "tokens_before": before,
            "tokens_after": after,
            "savings": before - after,
            "method": method,
        })

    def detect_saw_tooth(self) -> dict:
        """分析 token 历史，检测锯齿模式。

        Returns:
            {
                "pattern_detected": bool,
                "pattern_type": str,        # "saw_tooth", "monotonic_up", "flat", "unknown"
                "last_build_up_ratio": float,  # 最近上升幅度比
                "peak_tokens": int,            # 窗口内峰值
                "current_tokens": int,         # 当前 token 数
                "compress_savings_avg": float,  # 平均压缩节省
            }
        """
        history = list(self._token_history)
        if len(history) < 3:
            return {
                "pattern_detected": False,
                "pattern_type": "unknown",
                "last_build_up_ratio": 0.0,
                "peak_tokens": max(history) if history else 0,
                "current_tokens": history[-1] if history else 0,
                "compress_savings_avg": 0.0,
            }

        # 计算近期的上升/下降模式
        diffs = [history[i] - history[i - 1] for i in range(1, len(history))]
        up_count = sum(1 for d in diffs if d > 0)
        down_count = sum(1 for d in diffs if d < 0)

        # 锯齿模式：上升和下降交替出现
        if up_count >= 2 and down_count >= 1:
            # 检查交替性
            alternations = 0
            for i in range(1, len(diffs)):
                if (diffs[i] > 0 and diffs[i - 1] < 0) or (diffs[i] < 0 and diffs[i - 1] > 0):
                    alternations += 1

            if alternations >= 1:
                # 计算最近的 build-up 比
                last_peak = max(history[-3:]) if len(history) >= 3 else max(history)
                last_valley = min(history[-3:]) if len(history) >= 3 else min(history)
                build_up_ratio = (last_peak - last_valley) / max(last_valley, 1)

                pattern_type = "saw_tooth"

                # 检查最近保存事件
                savings_avg = 0.0
                if self._compress_events:
                    savings_avg = sum(e["savings"] for e in self._compress_events[-3:]) / max(len(self._compress_events[-3:]), 1)

                return {
                    "pattern_detected": True,
                    "pattern_type": pattern_type,
                    "last_build_up_ratio": round(build_up_ratio, 3),
                    "peak_tokens": max(history),
                    "current_tokens": history[-1],
                    "compress_savings_avg": round(savings_avg, 1),
                    "up_count": up_count,
                    "down_count": down_count,
                    "alternations": alternations,
                }

        # 持续上升 → 需要压缩
        if up_count >= len(diffs) * 0.8:
            return {
                "pattern_detected": True,
                "pattern_type": "monotonic_up",
                "last_build_up_ratio": round(abs(diffs[-1]) / max(abs(history[-2]), 1), 3) if len(diffs) >= 1 else 0.0,
                "peak_tokens": max(history),
                "current_tokens": history[-1],
                "compress_savings_avg": 0.0,
            }

        # 平坦模式
        max_diff = max(abs(d) for d in diffs) if diffs else 0
        if max_diff < 10:
            return {
                "pattern_detected": False,
                "pattern_type": "flat",
                "last_build_up_ratio": 0.0,
                "peak_tokens": max(history),
                "current_tokens": history[-1],
                "compress_savings_avg": 0.0,
            }

        return {
            "pattern_detected": False,
            "pattern_type": "unknown",
            "last_build_up_ratio": 0.0,
            "peak_tokens": max(history),
            "current_tokens": history[-1],
            "compress_savings_avg": 0.0,
        }

    def get_stats(self) -> dict:
        return {
            "window_size": self._window_size,
            "samples": len(self._token_history),
            "compress_events": len(self._compress_events),
            "latest_pattern": self.detect_saw_tooth(),
        }


# ======================================================================
# SlimeMoldExplorer — 自主决定扩张或收缩
# ======================================================================

class SlimeMoldExplorer:
    """基于 Focus Agent 黏菌启发架构的自主探索决策器。

    黏菌的网络扩张/收缩策略:
    - 信息密度高（有用信息多）→ 扩张网络 → 保留更多上下文
    - 信息密度低（冗余/噪声多）→ 收缩网络 → 压缩到关键节点
    - 探索/利用平衡：在保留上下文完整性和节省 token 之间平衡

    信息密度计算基于:
    - 命名实体密度（引入新实体表示新信息）
    - 语义更新率（与之前内容的信息差异）
    - 动作/决策密度（指令和动作的频率）
    """

    def __init__(self, info_density_threshold: float = _DEFAULT_INFO_DENSITY_THRESHOLD,
                 explore_threshold: float = _DEFAULT_EXPLORE_THRESHOLD):
        self._info_density_threshold = info_density_threshold
        self._explore_threshold = explore_threshold
        self._decisions: list[dict] = []
        self._total_explored = 0
        self._total_consolidated = 0
        self._entropy_threshold = _DEFAULT_ENTROPY_THRESHOLD

    def estimate_information_density(self, text: str) -> float:
        """估算一段文本的信息密度 (0.0 ~ 1.0)。

        高信息密度特征:
        - 高命名实体密度（新实体 = 新信息）
        - 动作/指令密度
        - 领域特定术语密度
        - 数值和引用的密度

        低信息密度特征:
        - 重复短语
        - 衔接/过渡词
        - 冗长描述
        """
        if not text or len(text) < 5:
            return 0.0

        # 命名实体密度 — 大写词/数字代表实体
        entities = len(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text))
        numbers = len(re.findall(r'\b\d+[\.\d]*\b', text))
        entity_density = (entities + numbers) / max(len(text.split()), 1)

        # 动作密度 — 动词、命令式语句
        actions = len(re.findall(r'\b(?:run|exec|write|read|create|delete|update|'
                                r'call|send|fetch|compute|analyze|transform|build|'
                                r'deploy|compile|test|validate|search|find)\b',
                                text, re.IGNORECASE))
        action_density = actions / max(len(text.split()), 1)

        # 术语密度 — 领域特定词汇
        terms = len(re.findall(r'\b(?:function|class|method|API|endpoint|database|'
                              r'model|algorithm|config|schema|protocol|token|'
                              r'context|parameter|argument|response|request)\b',
                              text, re.IGNORECASE))
        term_density = terms / max(len(text.split()), 1)

        # 冗余度惩罚 — 重复词检测
        words = text.lower().split()
        if words:
            unique_ratio = len(set(words)) / len(words)
        else:
            unique_ratio = 1.0

        # 综合密度分数
        density = (entity_density * 0.35 + action_density * 0.30 +
                   term_density * 0.20 + unique_ratio * 0.15)

        return min(1.0, density * 3.0)  # 缩放并上限

    def should_explore(self, text: str, context_tokens: int,
                       max_tokens: int, saw_tooth_result: dict | None = None) -> dict:
        """决定是否继续探索（扩张上下文）或收缩（压缩）。

        Args:
            text: 当前文段
            context_tokens: 当前上下文的估计 token 数
            max_tokens: 最大 token 限制
            saw_tooth_result: 可选，锯齿检测结果

        Returns:
            {
                "action": "expand" | "consolidate" | "maintain",
                "confidence": float,
                "information_density": float,
                "reasons": list[str],
            }
        """
        density = self.estimate_information_density(text)
        usage_ratio = context_tokens / max(max_tokens, 1)
        reasons = []

        # 基础因素分析
        high_density = density >= self._explore_threshold
        low_density = density < self._info_density_threshold
        near_capacity = usage_ratio >= 0.85
        moderate_capacity = 0.5 <= usage_ratio < 0.85

        # 锯齿模式辅助决策
        saw_tooth_expanding = False
        if saw_tooth_result and saw_tooth_result.get("pattern_detected"):
            saw_tooth_expanding = saw_tooth_result.get("pattern_type") == "monotonic_up"

        confidence = abs(density - 0.5) * 2  # 离 0.5 越远，决策置信度越高

        if not text:
            return {"action": "maintain", "confidence": 0.0,
                    "information_density": 0.0, "reasons": ["Empty context"]}

        # 决策逻辑
        if low_density and (near_capacity or saw_tooth_expanding):
            action = "consolidate"
            reasons.append(f"Low info density ({density:.2f}) + near capacity ({usage_ratio:.0%})")
            if saw_tooth_expanding:
                reasons.append("Saw-tooth pattern detected — consolidation time")
            self._total_consolidated += 1

        elif high_density and not near_capacity:
            action = "expand"
            reasons.append(f"High info density ({density:.2f}) — preserving context")
            self._total_explored += 1

        elif low_density and not near_capacity:
            action = "maintain"
            reasons.append(f"Low density ({density:.2f}) but capacity available ({usage_ratio:.0%})")

        elif high_density and near_capacity:
            # 两难：高密度但容量不足 → 需要选择性压缩
            action = "consolidate"
            reasons.append(f"High density ({density:.2f}) but OOM risk ({usage_ratio:.0%})")
            self._total_consolidated += 1

        else:
            action = "maintain"
            reasons.append(f"Moderate density ({density:.2f}) at {usage_ratio:.0%} capacity")

        result = {
            "action": action,
            "confidence": round(min(1.0, confidence), 3),
            "information_density": round(density, 3),
            "reasons": reasons,
        }
        self._decisions.append(result)
        return result

    def should_consolidate(self, token_count: int, max_tokens: int = _DEFAULT_MAX_TOKENS,
                          text: str = "") -> dict:
        """基于 token 数量和信息密度阈值判断是否应压缩。

        Focus Agent 论文的核心决策函数：
        - 超过容量阈值 → 必须压缩
        - Shannon 熵低于阈值且容量紧张 → 主动压缩（信息冗余）
        - 两者都不满足 → 维持现状

        Args:
            token_count: 当前上下文的估计 token 数
            max_tokens: 最大允许 token 数（默认 _DEFAULT_MAX_TOKENS）
            text: 可选，用于计算实际 Shannon 熵和密度的文本

        Returns:
            {
                "consolidate": bool,
                "reason": str,
                "token_count": int,
                "usage_ratio": float,
                "shannon_entropy": float,
                "information_density": float,
            }
        """
        usage_ratio = token_count / max(max_tokens, 1)

        # 计算 Shannon 熵和信息密度（如果有文本）
        if text and len(text) >= 5:
            entropy = shannon_entropy(text)
            density = estimate_information_density(text)
        else:
            entropy = 0.0
            density = min(1.0, usage_ratio * 2.0)

        reasons: list[str] = []
        consolidate = False

        # 条件 1: 超过容量阈值
        if usage_ratio >= 0.85:
            reasons.append(f"Token count ({token_count}) exceeds 85% capacity ({max_tokens})")
            consolidate = True

        # 条件 2: 信息密度低 + 容量紧张
        if density < self._info_density_threshold and usage_ratio >= 0.6:
            reasons.append(
                f"Low info density ({density:.2f} < {self._info_density_threshold}) at {usage_ratio:.0%} capacity"
            )
            consolidate = True

        # 条件 3: 熵低（信息冗余）
        if entropy > 0 and entropy < self._entropy_threshold and usage_ratio >= 0.5:
            reasons.append(
                f"Low Shannon entropy ({entropy:.1f} < {self._entropy_threshold}) at {usage_ratio:.0%} capacity"
            )
            consolidate = True

        if not reasons:
            reasons.append(
                f"Sufficient capacity ({usage_ratio:.0%}), density={density:.2f}, entropy={entropy:.1f}"
            )

        if consolidate:
            self._total_consolidated += 1

        return {
            "consolidate": consolidate,
            "reason": "; ".join(reasons),
            "token_count": token_count,
            "usage_ratio": round(usage_ratio, 4),
            "shannon_entropy": round(entropy, 4),
            "information_density": round(density, 4),
        }

    def get_stats(self) -> dict:
        return {
            "explore_count": self._total_explored,
            "consolidate_count": self._total_consolidated,
            "decision_count": len(self._decisions),
            "explore_ratio": round(self._total_explored / max(len(self._decisions), 1), 3),
            "consolidate_ratio": round(self._total_consolidated / max(len(self._decisions), 1), 3),
        }


# ======================================================================
# FocusCompressor — 提取关键学习内容 (summarize, don't truncate)
# ======================================================================

class FocusCompressor:
    """基于关键学习提取的语义压缩器。

    与简单删除旧内容不同，该类从被压缩的部分中提取"关键学习"（key learnings）。
    模仿 Focus Agent 论文中的"consolidation"过程：
    1. 识别重要信息（命名实体、决策、结果、结论）
    2. 总结为精炼格式
    3. 保留关键关系而非原始文本

    支持多种压缩深度:
    - "light": 只移除冗余/重复，保留所有关键点
    - "medium" (默认): 提取关键学习，移除示例细节
    - "deep": 仅保留最高级别摘要
    """

    def __init__(self, min_learning_length: int = _DEFAULT_MIN_LEARNINGS_LENGTH):
        self._min_learning_length = min_learning_length
        self._compressions: list[dict] = []

    def compress_part(self, text: str, task_type: str = "general",
                      depth: str = "medium") -> str:
        """压缩一段文本并提取关键学习。

        Args:
            text: 原始文本
            task_type: 任务类型（"general", "code", "conversation", "analysis"）
            depth: 压缩深度 ("light", "medium", "deep")

        Returns:
            压缩后的文本，包含提取的关键学习
        """
        if not text or len(text) < self._min_learning_length:
            return text

        lines = text.split("\n")
        words = text.split()

        # 提取关键学习
        key_learnings = self._extract_key_learnings(text, task_type, depth)

        # 构建压缩格式
        if depth == "deep" and key_learnings:
            compressed = (
                "📌 Key Learnings:\n"
                + "\n".join(f"  • {k}" for k in key_learnings[:5])
                + "\n[compressed: focus-summary]"
            )
        elif depth in ("medium", "light") and key_learnings:
            # 保留前几行上下文 + 关键学习
            prefix_lines = []
            for line in lines:
                if line.strip() and len(prefix_lines) < 3:
                    prefix_lines.append(line)
                elif len(prefix_lines) >= 3:
                    break

            prefix = "\n".join(prefix_lines) if prefix_lines else "..."
            compressed = (
                prefix + "\n\n"
                + "📌 Key Learnings:\n"
                + "\n".join(f"  • {k}" for k in key_learnings[:7])
                + f"\n[compressed from {len(lines)} lines, {len(words)} words → focus-summary]"
            )
        else:
            # Fallback: 传统压缩
            if len(lines) > 3:
                compressed = (lines[0] + "\n... (" + str(len(lines) - 2)
                              + " lines compressed)\n" + lines[-1])
            elif len(words) > 30:
                compressed = " ".join(words[:15]) + "..." + " ".join(words[-5:])
            else:
                return text

        self._compressions.append({
            "original_length": len(words),
            "compressed_length": len(compressed.split()),
            "depth": depth,
            "task_type": task_type,
        })

        return compressed

    def _extract_key_learnings(self, text: str, task_type: str,
                               depth: str) -> list[str]:
        """从文本中提取关键学习点。"""
        lines = text.split("\n")
        learnings: list[str] = []

        if task_type == "code":
            learnings = self._extract_code_learnings(lines, depth)
        elif task_type == "conversation":
            learnings = self._extract_conversation_learnings(lines, depth)
        elif task_type == "analysis":
            learnings = self._extract_analysis_learnings(lines, depth)
        else:  # general
            learnings = self._extract_general_learnings(lines, depth)

        # 去重和过滤
        seen = set()
        unique = []
        for l in learnings:
            norm = l.lower().strip()
            if norm not in seen and len(norm) >= self._min_learning_length:
                seen.add(norm)
                unique.append(l)

        return unique

    def _extract_general_learnings(self, lines: list[str], depth: str) -> list[str]:
        """从一般文本提取关键学习。"""
        learnings = []
        # 搜索: 结论、决策、重要发现
        for line in lines:
            stripped = line.strip()
            # 决策标记
            if any(marker in stripped for marker in
                   ("conclusion", "summary", "result", "found that",
                    "therefore", "thus", "key insight", "important",
                    "decision", "chosen", "selected", "confirmed",
                    "✅", "❌", "→", "=>", "=>", "learned")):
                if len(stripped) > 10:
                    learnings.append(stripped[:200])

            # 带数字的发现
            if re.search(r'\d+[%×]', stripped) and len(stripped) > 15:
                learnings.append(stripped[:200])

            # 列表项通常是重要内容
            if stripped.startswith(("- ", "* ", "• ", "1. ", "2.")):
                if len(stripped) > 15:
                    learnings.append(stripped[:200])

        # deep: 只取前几个
        if depth == "deep":
            return learnings[:3]
        return learnings[:7]

    def _extract_code_learnings(self, lines: list[str], depth: str) -> list[str]:
        """从代码/技术文本提取关键学习。"""
        learnings = []
        function_names = []
        import_changes = []
        key_decisions = []

        for line in lines:
            stripped = line.strip()

            # 函数/类定义
            m = re.match(r'(?:def|class|async def)\s+(\w+)', stripped)
            if m:
                function_names.append(f"Defined {m.group(1)}")

            # 导入
            if stripped.startswith(("import ", "from ")):
                import_changes.append(stripped[:100])

            # 调试发现
            if any(kw in stripped.lower() for kw in
                   ("bug", "fix", "issue", "error", "root cause",
                    "solution", "workaround", "refactored")):
                key_decisions.append(stripped[:200])

            # 配置更改
            if any(kw in stripped.lower() for kw in
                   ("config", "setting", "parameter", "changed from",
                    "renamed", "migrated")):
                key_decisions.append(stripped[:200])

        if depth == "deep":
            return (function_names[:3] + key_decisions[:2])
        return (["Code changes: " + "; ".join(function_names[:5])] if function_names else []) \
               + import_changes[:2] + key_decisions[:3]

    def _extract_conversation_learnings(self, lines: list[str], depth: str) -> list[str]:
        """从对话文本提取关键学习。"""
        learnings = []
        for line in lines:
            stripped = line.strip()
            # 用户请求中的关键信息
            if any(marker in stripped.lower() for marker in
                   ("i need", "please", "can you", "goal:", "objective:",
                    "requirement", "constraint", "prefer", "must", "should")):
                if len(stripped) > 15 and len(stripped) < 300:
                    learnings.append(stripped)

            # 决策点
            if re.match(r'^(?:ok|yes|no|sure|agreed|confirmed|done)\b', stripped, re.I):
                if len(stripped) > 20:
                    learnings.append("Decision: " + stripped[:200])

        if depth == "deep":
            return learnings[:3]
        return learnings[:7]

    def _extract_analysis_learnings(self, lines: list[str], depth: str) -> list[str]:
        """从分析文本提取关键学习。"""
        learnings = []
        for line in lines:
            stripped = line.strip()
            # 统计/比较/结论
            if any(marker in stripped.lower() for marker in
                   ("compared to", "higher than", "lower than", "significant",
                    "correlation", "difference", "trend", "pattern",
                    "average", "median", "distribution", "outlier")):
                learnings.append(stripped[:250])
            # 数字驱动结论
            if re.search(r'\d+[.%]', stripped) and any(
                m in stripped.lower() for m in ("increase", "decrease", "reduction",
                                                 "growth", "improvement", "decline")):
                learnings.append(stripped[:250])

        if depth == "deep":
            return learnings[:3]
        return learnings[:7]

    def get_stats(self) -> dict:
        if not self._compressions:
            return {"total_compressions": 0}
        total_orig = sum(c["original_length"] for c in self._compressions)
        total_comp = sum(c["compressed_length"] for c in self._compressions)
        return {
            "total_compressions": len(self._compressions),
            "total_words_before": total_orig,
            "total_words_after": total_comp,
            "avg_savings_pct": round(
                (1 - total_comp / max(total_orig, 1)) * 100, 1
            ) if total_orig > 0 else 0,
        }


# ======================================================================
# ActiveCompressor — 扩展版，集成 Focus Agent 组件
# ======================================================================

class ActiveCompressor:
    """主动上下文压缩器，集成 Focus Agent 黏菌启发式组件。

    在原有阈值触发压缩基础上，增加:
    - SawToothDetector: 监测 token 使用量锯齿模式
    - SlimeMoldExplorer: 基于信息密度的自主探索决策
    - FocusCompressor: 提取关键学习而非简单删除
    """

    def __init__(self, max_tokens: int = _DEFAULT_MAX_TOKENS,
                 compression_ratio: float = _DEFAULT_COMPRESSION_RATIO,
                 saw_tooth_threshold: float = _DEFAULT_SAW_TOOTH_THRESHOLD,
                 enable_focus: bool = True):
        self._max_tokens = max_tokens
        self._compression_ratio = compression_ratio
        self._saw_tooth_threshold = saw_tooth_threshold
        self._compress_count = 0
        self._total_tokens_before = 0
        self._total_tokens_after = 0

        # Focus Agent 组件
        self.enable_focus = enable_focus
        self.saw_tooth_detector = SawToothDetector()
        self.slime_mold = SlimeMoldExplorer()
        self.focus_compressor = FocusCompressor()

    def estimate_tokens(self, text: str) -> int:
        """估算文本 token 数（近似：英文词数×1.3 + 中文字符数）。"""
        if not text:
            return 0
        english_words = len(re.findall(r'[a-zA-Z]+', text))
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        return int(english_words * 1.3 + chinese_chars)

    def should_compress(self, context: list[str]) -> bool:
        """判断是否需要压缩。

        使用 Focus Agent 的黏菌探索 + 原有阈值触发双重判断。
        """
        total = sum(self.estimate_tokens(c) for c in context)
        if total == 0:
            return False
        usage_ratio = total / self._max_tokens

        # 阈值触发（原有）
        if usage_ratio >= self._saw_tooth_threshold:
            return True

        # Focus Agent 自主决策（新增）
        if self.enable_focus and context:
            latest_text = context[-1] if context else ""
            saw_tooth = self.saw_tooth_detector.detect_saw_tooth()
            decision = self.slime_mold.should_explore(
                latest_text, total, self._max_tokens, saw_tooth
            )
            if decision["action"] == "consolidate" and decision["confidence"] > 0.5:
                logger.debug("Focus Agent autonomously decided to consolidate")
                return True

        return False

    def compress(self, context: list[str], task_type: str = "general") -> list[str]:
        """压缩上下文，使用 Focus Agent 压缩器提取关键学习。

        Args:
            context: 上下文文本列表
            task_type: "general", "code", "conversation", "analysis"

        Returns:
            压缩后的上下文列表
        """
        if not context:
            return []

        total_before = sum(self.estimate_tokens(c) for c in context)
        self._total_tokens_before += total_before

        # 记录 token 历史用于锯齿检测
        if self.enable_focus:
            for c in context:
                self.saw_tooth_detector.record(self.estimate_tokens(c))

        # 选择压缩方法
        if self.enable_focus:
            compressed_context = self._focus_compress(context, task_type, total_before)
        else:
            compressed_context = self._legacy_compress(context, task_type)

        total_after = sum(self.estimate_tokens(c) for c in compressed_context)
        self._total_tokens_after += total_after

        logger.debug("Compressed: %d→%d tokens (%.1f%%) [focus=%s]",
                     total_before, total_after,
                     (1 - total_after / max(total_before, 1)) * 100,
                     self.enable_focus)

        return compressed_context

    def _focus_compress(self, context: list[str], task_type: str,
                        total_before: int) -> list[str]:
        """Focus Agent 压缩：提取关键学习而非删除。"""
        n_compress = max(1, int(len(context) * self._compression_ratio))

        # 优先压缩较老的内容
        compress_candidates = context[:len(context) // 3]
        if not compress_candidates:
            compress_candidates = context[:n_compress]

        result = list(context)
        compressed_count = 0

        for i, part in enumerate(compress_candidates[:n_compress]):
            compressed = self.focus_compressor.compress_part(part, task_type)
            if compressed != part:
                # Find and replace in result
                idx = result.index(part) if part in result else -1
                if idx >= 0:
                    result[idx] = compressed
                    compressed_count += 1

        # 记录锯齿压缩事件
        if self.enable_focus:
            total_after = sum(self.estimate_tokens(c) for c in result)
            self.saw_tooth_detector.record_compress(total_before, total_after)

        self._compress_count += compressed_count
        return result

    def _legacy_compress(self, context: list[str], task_type: str) -> list[str]:
        """原有压缩方法：基于截断的简单压缩。"""
        n_compress = max(1, int(len(context) * self._compression_ratio))

        compress_candidates = context[:len(context) // 3]
        if not compress_candidates:
            compress_candidates = context[:n_compress]

        result = list(context)
        for i, part in enumerate(compress_candidates[:n_compress]):
            compressed = self._compress_part_legacy(part, task_type)
            idx = result.index(part) if part in result else -1
            if idx >= 0:
                result[idx] = compressed

        self._compress_count += min(n_compress, len(compress_candidates))
        return result

    def _compress_part_legacy(self, text: str, task_type: str) -> str:
        """原有压缩逻辑（保留为 fallback）。"""
        if len(text) < 50:
            return text
        lines = text.split("\n")
        if len(lines) > 3:
            return lines[0] + "\n... (" + str(len(lines) - 2) + " lines omitted)\n" + lines[-1]
        words = text.split()
        if len(words) > 30:
            return " ".join(words[:15]) + "..." + " ".join(words[-5:])
        return text

    def estimate_savings(self, context: list[str]) -> float:
        total = sum(self.estimate_tokens(c) for c in context)
        if total == 0:
            return 0.0
        n = max(1, int(len(context) * self._compression_ratio))
        avg_len = total / len(context)
        return (n * avg_len * 0.3) / total

    def get_stats(self) -> dict:
        focus_stats = {}
        if self.enable_focus:
            focus_stats = {
                "saw_tooth": self.saw_tooth_detector.get_stats(),
                "slime_mold": self.slime_mold.get_stats(),
                "focus_compressor": self.focus_compressor.get_stats(),
            }
        return {
            "compress_count": self._compress_count,
            "tokens_before": self._total_tokens_before,
            "tokens_after": self._total_tokens_after,
            "savings_pct": round(
                (1 - self._total_tokens_after / max(self._total_tokens_before, 1)) * 100, 1
            ) if self._total_tokens_before > 0 else 0,
            "focus_enabled": self.enable_focus,
            "focus": focus_stats,
        }

    def get_compression_history(self) -> list[dict]:
        """获取压缩历史记录，支持锯齿模式追踪。

        Focus Agent 论文依赖历史压缩模式来判断未来的压缩时机。
        每次调用返回完整的压缩事件序列，可用于:

        - 可视化 token 使用量的锯齿模式
        - 检测压缩频率是否过高或过低
        - 计算平均压缩间隔和幅度

        Returns:
            按时间顺序排列的压缩事件列表，每个包含:
            - timestamp: 事件时间戳
            - tokens_before: 压缩前总 token 数
            - tokens_after: 压缩后总 token 数
            - savings: 节省的 token 数
            - method: 压缩方法 (\"threshold\", \"focus\", \"legacy\")
            - pattern_type: 当时的锯齿模式类型
            - pattern_detected: 是否检测到锯齿模式
        """
        # 从 SawToothDetector 获取压缩事件
        raw_events: list[dict] = []
        if self.enable_focus:
            raw_events = list(self.saw_tooth_detector._compress_events)

        # 补充锯齿模式信息
        history: list[dict] = []
        for event in raw_events:
            pattern = self.saw_tooth_detector.detect_saw_tooth()
            history.append({
                "timestamp": event.get("timestamp", 0.0),
                "tokens_before": event.get("tokens_before", 0),
                "tokens_after": event.get("tokens_after", 0),
                "savings": event.get("savings", 0),
                "method": event.get("method", "unknown"),
                "pattern_type": pattern.get("pattern_type", "unknown"),
                "pattern_detected": pattern.get("pattern_detected", False),
            })

        # 如果没有 Focus 事件，从自身的统计数据构建一条摘要
        if not history and self._compress_count > 0:
            history.append({
                "timestamp": time.time(),
                "tokens_before": self._total_tokens_before,
                "tokens_after": self._total_tokens_after,
                "savings": self._total_tokens_before - self._total_tokens_after,
                "method": "legacy",
                "pattern_type": "unknown",
                "pattern_detected": False,
            })

        return history

    def analyze_saw_tooth_pattern(self) -> dict:
        """分析锯齿模式并提供可操作的洞察。

        基于 get_compression_history() 的数据，计算:

        - build_phase_avg: 平均积累阶段 token 增长率
        - compress_phase_avg: 平均压缩阶段 token 节省率
        - cycle_count: 完整 build-compress 周期数
        - frequency: 压缩频率（每 N 次调用一次压缩）
        - recommendation: 建议（加速/减速/维持压缩）

        Returns:
            锯齿模式分析结果字典
        """
        history = self.get_compression_history()
        pattern = self.saw_tooth_detector.detect_saw_tooth()

        if not history:
            return {
                "cycle_count": 0,
                "frequency": 0.0,
                "build_phase_avg": 0.0,
                "compress_phase_avg": 0.0,
                "recommendation": "insufficient_data",
                "current_pattern": pattern.get("pattern_type", "unknown"),
            }

        # 计算平均压缩节省
        savings_pcts = []
        for h in history:
            before = h["tokens_before"]
            if before > 0:
                savings_pcts.append(h["savings"] / before)

        avg_savings = sum(savings_pcts) / len(savings_pcts) if savings_pcts else 0.0

        # 计算压缩频率
        total_events = len(history)
        frequency = total_events / max(total_events, 1)  # arbitrary scale

        # 判断模式
        rec = "maintain"
        if pattern.get("pattern_type") == "monotonic_up" and avg_savings < 0.2:
            rec = "increase_compression"
        elif pattern.get("pattern_type") == "flat":
            rec = "maintain"
        elif avg_savings > 0.5:
            rec = "reduce_compression"

        return {
            "cycle_count": total_events,
            "frequency": round(frequency, 3),
            "build_phase_avg": round(pattern.get("last_build_up_ratio", 0.0), 4),
            "compress_phase_avg": round(avg_savings * 100, 1),
            "current_pattern": pattern.get("pattern_type", "unknown"),
            "recommendation": rec,
        }
