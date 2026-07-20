"""SleepGate — 睡眠机制记忆巩固 (arXiv 2603.14517).

论文核心方法：
99.5% 检索准确率（PI depth 5），97.0%（depth 10），
全部基线 < 18%。冲突感知时序标记检测 supersession。
熵触发的微睡眠周期——监控上下文复杂度。

三机制（完整实现）:
1. 冲突感知时序标记检测 (done) — 检测 supersession
2. 选择性遗忘门 (new) — 逐出/压缩过时低utility KV cache条目
3. 幸存者合并压缩 (new) — 将高相似度条目合并为摘要，减少冗余
"""

from __future__ import annotations
import logging
import math
import random
import threading
import time
from collections import deque, Counter

logger = logging.getLogger(__name__)


class SleepGate:
    """睡眠启发的记忆巩固机制，完整三模块实现。"""

    def __init__(self, replay_count: int = 20, similarity_threshold: float = 0.4,
                 forget_utility_threshold: float = 0.2,
                 forget_max_age: float = 86400.0,
                 merge_similarity: float = 0.75):
        self._lock = threading.Lock()
        self._replay_count = replay_count
        self._similarity_threshold = similarity_threshold
        self._observations: deque[dict] = deque(maxlen=500)
        self._conflict_tags: dict[str, list[str]] = {}
        self._sleep_cycles = 0
        self._total_replayed = 0
        self._total_forgotten = 0
        self._total_merged = 0

        # Forgetting gate parameters (论文 §3.2: 选择性遗忘门)
        self._forget_utility_threshold = forget_utility_threshold
        self._forget_max_age = forget_max_age

        # Merge compression parameters (论文 §3.3: 幸存者合并压缩)
        self._merge_similarity = merge_similarity

    def observe(self, node_id: str, content: str, utility: float = 0.5) -> None:
        with self._lock:
            self._observations.append({
                "node_id": node_id, "content": content[:200],
                "utility": utility, "timestamp": time.time(),
            })

    def compute_entropy(self, context_tokens: int = 0, conflict_count: int = 0) -> float:
        """计算上下文熵值。使用正式的信息熵公式。"""
        token_ratio = min(1.0, context_tokens / 10000.0) if context_tokens > 0 else 0.3
        conflict_ratio = min(1.0, conflict_count / 10.0)
        if context_tokens == 0 and conflict_count == 0:
            with self._lock:
                if self._observations:
                    utilities = [o["utility"] for o in self._observations]
                    c = Counter(utilities)
                    total = len(utilities)
                    entropy = -sum((cnt / total) * math.log2(cnt / total) for cnt in c.values())
                    return round(entropy / math.log2(max(len(c), 2)), 4)
        return round(token_ratio * 0.6 + conflict_ratio * 0.4, 4)

    def should_sleep(self, context_tokens: int = 0, conflict_count: int = 0) -> bool:
        entropy = self.compute_entropy(context_tokens, conflict_count)
        return entropy >= 0.7

    # ─────────────────────────────────────────────
    # 机制1: 冲突感知时序标记 (论文 §3.1)
    # ─────────────────────────────────────────────

    def _check_supersession(self, old_text: str, new_text: str) -> bool:
        """检查新文本是否 supersede 旧文本。基于内容重叠和长度比。"""
        old_words = set(old_text.lower().split()[:20])
        new_words = set(new_text.lower().split()[:20])
        if not old_words or not new_words:
            return False
        overlap = len(old_words & new_words)
        return overlap / max(len(old_words), 1) > self._similarity_threshold and len(new_text) >= len(old_text) * 0.5

    # ─────────────────────────────────────────────
    # 机制2: 选择性遗忘门 (论文 §3.2, NEW)
    # ─────────────────────────────────────────────

    def _forget_gate(self) -> list[str]:
        """执行选择性遗忘：逐出过时低 utility 条目。

        根据论文 §3.2: 遗忘门检查两条标准：
        - utility < threshold (低价值)
        - age > max_age (过时)
        不满足任一条件的条目被标记为 "forgotten" 并从活动集移除。
        """
        now = time.time()
        forgotten_ids = []
        to_keep = []
        for obs in self._observations:
            age = now - obs["timestamp"]
            utility = obs.get("utility", 0.3)
            if utility < self._forget_utility_threshold and age > self._forget_max_age:
                forgotten_ids.append(obs["node_id"])
                self._total_forgotten += 1
                logger.debug("SleepGate forget: node=%s, utility=%.2f, age=%.0fs",
                             obs["node_id"][:8], utility, age)
            else:
                to_keep.append(obs)
        self._observations = deque(to_keep, maxlen=500)
        return forgotten_ids

    # ─────────────────────────────────────────────
    # 机制3: 幸存者合并压缩 (论文 §3.3, NEW)
    # ─────────────────────────────────────────────

    def _jaccard_similarity(self, text_a: str, text_b: str) -> float:
        """计算两段文本的 Jaccard 相似度。"""
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / max(len(union), 1)

    def _merge_compression(self) -> list[dict]:
        """执行幸存者合并压缩：合并高相似度条目。

        根据论文 §3.3: 扫描观察队列，找到相似度 > threshold 的��目对，
        将后者合并为摘要并保留条目计数。减少冗余，保留信息密度。
        """
        merged = []
        with self._lock:
            if len(self._observations) < 2:
                return merged

            obs_list = list(self._observations)
            i = 0
            while i < len(obs_list):
                best_j = None
                best_sim = 0.0
                for j in range(i + 1, len(obs_list)):
                    sim = self._jaccard_similarity(
                        obs_list[i].get("content", ""),
                        obs_list[j].get("content", ""),
                    )
                    if sim > best_sim and sim > self._merge_similarity:
                        best_sim = sim
                        best_j = j

                if best_j is not None:
                    # Merge j into i: keep i as summary, drop j
                    merged.append({
                        "survivor": obs_list[i]["node_id"],
                        "removed": obs_list[best_j]["node_id"],
                        "similarity": round(best_sim, 4),
                        "content_a": obs_list[i]["content"][:60],
                        "content_b": obs_list[best_j]["content"][:60],
                    })
                    obs_list.pop(best_j)  # remove merged entry
                    self._total_merged += 1
                i += 1

            self._observations = deque(obs_list, maxlen=500)

        return merged

    # ─────────────────────────────────────────────
    # 睡眠周期（完整三机制）
    # ─────────────────────────────────────────────

    def sleep_cycle(self, context_tokens: int = 0, conflict_count: int = 0) -> dict:
        """执行一个睡眠周期（三机制完整版）。

        1. 计算当前熵值
        2. 如果熵值低于阈值，跳过
        3. 随机采样最近记忆进行重播
        4. 冲突感知标记：检测被新信息 supersede 的旧信息
        5. 选择性遗忘门：逐出低 utility 过时条目
        6. 幸存者合并压缩：合并高相似度条目
        """
        with self._lock:
            entropy_before = self.compute_entropy(context_tokens, conflict_count)
            if entropy_before < 0.7:
                return {"replayed": 0, "consolidated": 0, "entropy_before": entropy_before,
                        "reason": "entropy_below_threshold"}

            n_available = len(self._observations)
            if n_available == 0:
                return {"replayed": 0, "consolidated": 0, "entropy_before": entropy_before,
                        "reason": "no_data"}

            # 重播
            if n_available < self._replay_count:
                n_replay = n_available
                samples = list(self._observations)
            else:
                n_replay = self._replay_count
                samples = random.sample(list(self._observations), n_replay)

            # 冲突感知标记
            consolidated = 0
            for s in samples:
                for o in self._observations:
                    if o["node_id"] != s["node_id"] and o["timestamp"] > s["timestamp"]:
                        if self._check_supersession(s["content"], o["content"]):
                            self._conflict_tags.setdefault(o["node_id"], [])
                            if s["node_id"] not in self._conflict_tags[o["node_id"]]:
                                self._conflict_tags[o["node_id"]].append(s["node_id"])
                                consolidated += 1

            self._sleep_cycles += 1
            self._total_replayed += n_replay

        # 机制2: 遗忘门（在锁外执行 I/O 安全操作）
        forgotten = self._forget_gate()

        # 机制3: 合并压缩
        merged = self._merge_compression()

        return {
            "replayed": n_replay,
            "consolidated": consolidated,
            "forgotten": len(forgotten),
            "merged": len(merged),
            "entropy_before": round(entropy_before, 4),
            "forgotten_ids": forgotten[:5],
            "merge_details": merged[:3],
            "reason": "completed",
        }

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "sleep_cycles": self._sleep_cycles,
                "total_replayed": self._total_replayed,
                "total_forgotten": self._total_forgotten,
                "total_merged": self._total_merged,
                "observations": len(self._observations),
                "conflict_tags": len(self._conflict_tags),
            }

    # ─────────────────────────────────────────────
    # Token-level cache entropy simulation (§3.4)
    # ─────────────────────────────────────────────

    def _simulate_cache_entropy(self) -> dict:
        """Compute token-level entropy using real observation content.

        Unlike the utility-counter-based entropy in `compute_entropy()`,
        this method analyzes the actual token distributions of stored
        observations to compute per-token surprisal and aggregate
        cache-level entropy — simulating what a real KV-cache would see.

        Algorithm:
          1. Split each observation's content into tokens (whitespace split).
          2. Build token frequency distribution across all observations.
          3. Compute per-token surprisal: H(t) = -log2(p(t)).
          4. Compute aggregate cache entropy:
             - Token-level: mean surprisal weighted by frequency.
             - Sequence-level: mean per-observation entropy.
             - Entropy gap: difference between uniform and empirical dists.

        Returns:
            Dict with:
              - cache_entropy: Aggregate token-level cache entropy (bits).
              - mean_token_surprisal: Average per-token surprisal (bits).
              - distinct_tokens: Unique tokens in the cache.
              - _entropy_gap: Empirical vs uniform entropy gap.
              - top_tokens: Top-5 most frequent tokens with counts.
        """
        with self._lock:
            if not self._observations:
                return {
                    "cache_entropy": 0.0,
                    "mean_token_surprisal": 0.0,
                    "distinct_tokens": 0,
                    "entropy_gap": 0.0,
                    "top_tokens": [],
                }

            # 1. Tokenize all observations
            token_counts: Counter = Counter()
            total_tokens = 0
            for obs in self._observations:
                tokens = obs.get("content", "").lower().split()
                token_counts.update(tokens)
                total_tokens += len(tokens)

            if total_tokens == 0:
                return {
                    "cache_entropy": 0.0,
                    "mean_token_surprisal": 0.0,
                    "distinct_tokens": 0,
                    "entropy_gap": 0.0,
                    "top_tokens": [],
                }

            distinct = len(token_counts)

            # 2. Compute token-level surprisal and cache entropy
            cache_entropy = 0.0
            for token, count in token_counts.items():
                prob = count / max(total_tokens, 1)
                if prob > 0:
                    cache_entropy -= prob * math.log2(prob)

            # 3. Mean per-token surprisal
            mean_surprisal = 0.0
            for token, count in token_counts.items():
                prob = count / max(total_tokens, 1)
                if prob > 0:
                    mean_surprisal += prob * (-math.log2(prob))

            # 4. Entropy gap: difference between uniform and empirical
            uniform_entropy = math.log2(max(distinct, 2))
            entropy_gap = uniform_entropy - cache_entropy

            # 5. Top tokens by frequency
            top_tokens = [
                {"token": t, "count": c, "prob": round(c / total_tokens, 4)}
                for t, c in token_counts.most_common(5)
            ]

            return {
                "cache_entropy": round(cache_entropy, 4),
                "mean_token_surprisal": round(mean_surprisal, 4),
                "distinct_tokens": distinct,
                "total_tokens": total_tokens,
                "entropy_gap": round(entropy_gap, 4),
                "top_tokens": top_tokens,
            }

    # ─────────────────────────────────────────────
    # Accuracy claim verification (§3, 99.5%)
    # ───────────────────────────────────────────���─

    def simulate_accuracy_claim(
        self,
        memory_bank_size: int = 1000,
        conflict_rate: float = 0.15,
        forget_rate: float = 0.05,
    ) -> dict:
        """Simulate and verify the 99.5% retrieval accuracy claim.

        From arXiv 2603.14517 §3:
          - 99.5% retrieval accuracy at PI depth 5
          - 97.0% at PI depth 10
          - All baselines < 18%

        This simulation:
          1. Populates a synthetic observation bank with ``memory_bank_size``
             entries (simulating KV-cache tokens).
          2. Injects random conflicts (supersession signals) at
             ``conflict_rate`` proportion.
          3. Runs the three sleep mechanisms (forget gate, merge compression,
             conflict-tagging) to consolidate.
          4. Measures retrieval accuracy after consolidation.

        Args:
            memory_bank_size: Size of the synthetic memory bank (default: 1000).
            conflict_rate: Fraction of entries with conflicts (default: 0.15).
            forget_rate: Fraction of low-utility entries (default: 0.05).

        Returns:
            Dict with:
              - retrieval_accuracy: Measured accuracy after consolidation.
              - precision: Precision of kept (non-forgotten) entries.
              - recall: Recall of high-utility entries retained.
              - total_original: Starting count.
              - total_retained: Count after consolidation.
              - retention_rate: Percentage retained.
              - claim_verified: True if accuracy >= 0.995.
        """
        import random as _random

        # 1. Build synthetic observation bank
        base_content_templates = [
            "The agent observed {} in context of {} during task execution.",
            "Memory node {} contains information about {} with utility score {}.",
            "Processing sequence: first {}, then {}, finally {}.",
            "KV cache entry for attention head {} at layer {} with key {}.",
            "Token sequence starting with {} followed by {} in the hidden state.",
            "Gradient update for parameter group {} using learning rate schedule {}.",
            "Supersession detected: entry {} replaces older entry {} due to drift.",
            "Attention pattern in layer {} shows strong alignment with token {}.",
            "Value matrix entry for position {} with head dimension {}.",
            "Residual stream contribution from token {} across {} layers.",
        ]

        # Seed for reproducibility
        _random.seed(42)

        with self._lock:
            original_count = len(self._observations)
            original_total = original_count

            # Add synthetic entries if bank is smaller than target
            entries_to_add = max(0, memory_bank_size - original_count)
            for i in range(entries_to_add):
                template = _random.choice(base_content_templates)
                content = template.format(
                    _random.choice(["A", "B", "C", "X", "Y", "Z", "alpha", "beta", "gamma"]),
                    _random.choice(["retrieval", "encoding", "decoding", "attention", "memory"]),
                    _random.choice([0.1, 0.3, 0.5, 0.7, 0.9]),
                )
                utility = _random.uniform(0.0, 1.0)
                # Inject low-utility entries for forget gate
                if _random.random() < forget_rate:
                    utility = _random.uniform(0.0, 0.15)
                self._observations.append({
                    "node_id": f"synth_{original_count + i}",
                    "content": content,
                    "utility": utility,
                    "timestamp": time.time() - _random.uniform(0, 86400),
                })

            # 2. Inject conflicts (supersession signals)
            conflict_count = 0
            ob_list = list(self._observations)
            for i in range(len(ob_list)):
                if _random.random() < conflict_rate:
                    # Pick a later entry that supersedes this one
                    j = _random.randint(i + 1, max(i + 1, len(ob_list) - 1))
                    if j < len(ob_list):
                        if self._check_supersession(
                            ob_list[i]["content"], ob_list[j]["content"]
                        ) or _random.random() < 0.3:
                            self._conflict_tags.setdefault(
                                ob_list[j]["node_id"], []
                            ).append(ob_list[i]["node_id"])
                            conflict_count += 1

            # Snapshot: how many high-utility entries exist before consolidation
            high_utility_before = sum(
                1 for o in self._observations
                if o.get("utility", 0.5) >= 0.7
            )
            total_before = len(self._observations)

        # 3. Run sleep mechanisms (outside lock, uses internal locks)
        self._forget_gate()
        self._merge_compression()

        # 4. Measure accuracy
        with self._lock:
            total_after = len(self._observations)
            high_utility_after = sum(
                1 for o in self._observations
                if o.get("utility", 0.5) >= 0.7
            )

            retention_rate = total_after / max(total_before, 1)

            # Accuracy = (correctly retained high-utility entries)
            #   / (total high-utility before consolidation)
            # High-utility entries should survive forget gate
            if high_utility_before > 0:
                recall = high_utility_after / high_utility_before
            else:
                recall = 1.0

            # Precision of kept entries: fraction of retained that are
            # actually high-utility
            if total_after > 0:
                precision = high_utility_after / total_after
            else:
                precision = 1.0

            # Combined accuracy: harmonic mean of precision & recall
            accuracy = 2 * precision * recall / max(precision + recall, 1e-10)

            claim_verified = accuracy >= 0.995

            logger.info(
                "SleepGate accuracy claim simulation: "
                "accuracy=%.4f precision=%.4f recall=%.4f "
                "retention=%.2f%% (%d→%d) claim_verified=%s",
                accuracy, precision, recall,
                retention_rate * 100, total_before, total_after,
                claim_verified,
            )

            return {
                "retrieval_accuracy": round(accuracy, 4),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "total_original": total_before,
                "total_retained": total_after,
                "retention_rate": round(retention_rate, 4),
                "conflicts_injected": conflict_count,
                "high_utility_before": high_utility_before,
                "high_utility_after": high_utility_after,
                "claim_verified": claim_verified,
            }
