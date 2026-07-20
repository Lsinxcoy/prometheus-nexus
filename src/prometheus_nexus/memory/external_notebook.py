"""ExternalNotebook — 外部化私有笔记本 + Lewis Signaling Game。

在 multi-agent 场景中持久化线程安全的私有键值存储，
记录协调中建立的共享约定、符号映射、或任意状态。
扩展了 Lewis Signaling Game 框架 (arXiv 2607.00233)，
包含 sender/receiver 智能体通过协调建立共享信号的完整实现。

参考: "From Signals to Structure" (arXiv 2607.00233) 中关于
私有笔记本架构的讨论——persistent private notebook 在有状态
interaction 中防止高容量信道下的协调崩溃。

当前实现:
- 纯 KV store（线程安全，带历史记录）
- Lewis signaling game 框架：sender 选择信号，receiver 解析含义
- 协调率 (coordination_rate) 度量
- 笔记本作为 signaling game 的后端存储
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class ExternalNotebook:
    """外部化私有笔记本，持久化协调约定。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._store: dict[str, str] = {}
        self._history: list[dict] = []
        self._read_count = 0
        self._write_count = 0

    def write(self, key: str, value: str) -> dict:
        """写入一条约定。"""
        with self._lock:
            old = self._store.get(key)
            self._store[key] = value
            self._write_count += 1
            self._history.append({
                "action": "write", "key": key, "old_value": old,
                "new_value": value[:50], "ts": time.time(),
            })
            return {"ack": True, "key": key}

    def read(self, key: str) -> str | None:
        """读取一条约定。"""
        with self._lock:
            self._read_count += 1
            return self._store.get(key)

    def get_all_keys(self) -> list[str]:
        with self._lock:
            return list(self._store.keys())

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._history.clear()

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._store),
                "reads": self._read_count,
                "writes": self._write_count,
            }

    def get_history(self, limit: int = 50) -> list[dict]:
        """返回最近的历史记录。"""
        with self._lock:
            return self._history[-limit:]

    def search(self, query: str) -> list[dict]:
        """根据键或值的内容搜索笔记本条目。"""
        with self._lock:
            results = []
            query_lower = query.lower()
            for key, value in self._store.items():
                if query_lower in key.lower() or query_lower in value.lower():
                    results.append({"key": key, "value": value[:200]})
            return results


# ---------------------------------------------------------------------------
# Lewis Signaling Game
# ---------------------------------------------------------------------------

class SignalingAgent:
    """单个智能体在 Lewis signaling game 中扮演 sender 或 receiver。

    每个智能体维护两份表格:
    - sender 表格: meaning → signal (如何编码含义为信号)
    - receiver 表格: signal → meaning (如何解码信号为含义)

    智能体使用外部笔记本作为持久化记忆，记录协调历史。
    """

    def __init__(self, name: str, notebook: ExternalNotebook | None = None,
                 exploration_rate: float = 0.1):
        """初始化智能体。

        Args:
            name: 智能体名称（用于笔记本中区分键空间）
            notebook: 可选的笔记本实例，用于持久化表格
            exploration_rate: 探索率（随机选择信号而不使用已有映射的概率）
        """
        self.name = name
        self._notebook = notebook
        self._exploration_rate = exploration_rate

        # 内部表格: meaning → signal (sender) 和 signal → meaning (receiver)
        self._sender_table: dict[str, str] = {}
        self._receiver_table: dict[str, str] = {}

        # 协调历史
        self._interactions: list[dict] = []
        self._successes = 0
        self._total_rounds = 0

    # --- Sender methods ---

    def encode(self, meaning: str, available_signals: list[str]) -> str:
        """作为 sender，将含义编码为信号。

        策略:
        1. 如果已有映射且不探索，使用已有的信号
        2. 否则随机选择一个可用信号
        3. 记录到笔记本（如可用）
        """
        if (meaning in self._sender_table
                and random.random() > self._exploration_rate):
            signal = self._sender_table[meaning]
            if signal in available_signals:
                return signal

        # 探索或映射不可用：随机选择
        signal = random.choice(available_signals) if available_signals else "SILENCE"

        # 更新表格
        self._sender_table[meaning] = signal

        # 持久化到笔记本
        if self._notebook is not None:
            key = f"{self.name}:sender:{meaning}"
            self._notebook.write(key, signal)

        return signal

    # --- Receiver methods ---

    def decode(self, signal: str) -> str | None:
        """作为 receiver，将信号解码为含义。

        策略:
        1. 如果已有映射，返回对应的含义
        2. 否则返回 None（需要学习）
        """
        meaning = self._receiver_table.get(signal)
        if meaning:
            return meaning

        # 检查笔记本
        if self._notebook is not None:
            keys = self._notebook.get_all_keys()
            for key in keys:
                if key.startswith(f"{self.name}:receiver:") and key.endswith(f":{signal}"):
                    value = self._notebook.read(key)
                    if value:
                        return value

        return None

    def learn_mapping(self, signal: str, meaning: str) -> None:
        """学习或更新 signal → meaning 映射。"""
        self._receiver_table[signal] = meaning
        if self._notebook is not None:
            key = f"{self.name}:receiver:{meaning}:{signal}"
            self._notebook.write(key, meaning[:50])

    def record_interaction(self, role: str, meaning: str, signal: str,
                           interpretation: str | None,
                           success: bool) -> None:
        """记录一次交互。"""
        self._successes += 1 if success else 0
        self._total_rounds += 1
        self._interactions.append({
            "role": role,
            "meaning": meaning,
            "signal": signal,
            "interpretation": interpretation,
            "success": success,
            "ts": time.time(),
        })

    def get_success_rate(self) -> float:
        """��回该智能体的成功协调率。"""
        if self._total_rounds == 0:
            return 0.0
        return self._successes / self._total_rounds

    def get_sender_table(self) -> dict[str, str]:
        """返回 sender 表格的快照。"""
        return dict(self._sender_table)

    def get_receiver_table(self) -> dict[str, str]:
        """返回 receiver 表格的快照。"""
        return dict(self._receiver_table)

    def get_stats(self) -> dict[str, Any]:
        """返回智能体统计。"""
        return {
            "name": self.name,
            "total_rounds": self._total_rounds,
            "successes": self._successes,
            "success_rate": self.get_success_rate(),
            "sender_entries": len(self._sender_table),
            "receiver_entries": len(self._receiver_table),
            "exploration_rate": self._exploration_rate,
        }


class LewisSignalingGame:
    """Lewis signaling game 框架。

    两个智能体（sender 和 receiver）在一组含义和一组信号之间
    建立协调的映射关系。Sender 看到含义，选择一个信号发送；
    Receiver 接收信号，解读为含义。当 receiver 的解读与 sender
    的原始含义一致时，协调成功。

    这模拟了语言从无到有的涌现过程——智能体仅通过交互历史
    建立共享的符号系统 (Lewis, 1969; Skyrms, 2010)��

    Usage:
        game = LewisSignalingGame()
        game.setup_meanings(["food", "danger", "shelter"])
        game.setup_signals(["A", "B", "C"])

        for _ in range(100):
            success = game.play_round()
            print(f"协调率: {game.coordination_rate:.2f}")

        # 检查建立的映射
        mappings = game.get_established_mappings()
    """

    def __init__(self, notebook: ExternalNotebook | None = None,
                 sender_name: str = "sender",
                 receiver_name: str = "receiver",
                 exploration_rate: float = 0.1):
        """初始化 signaling game。

        Args:
            notebook: 可选的笔记本实例（持久化协调状态）
            sender_name: sender 智能体名称
            receiver_name: receiver 智能体名称
            exploration_rate: 探索率
        """
        if notebook is None:
            notebook = ExternalNotebook()
        self._notebook = notebook

        self._sender = SignalingAgent(sender_name, notebook, exploration_rate)
        self._receiver = SignalingAgent(receiver_name, notebook, exploration_rate)

        self._meanings: list[str] = []
        self._signals: list[str] = []
        self._round_history: list[dict] = []
        self._total_rounds = 0
        self._successful_rounds = 0

        # 交叉验证：含义级协调率追踪
        self._meaning_success: dict[str, list[bool]] = defaultdict(list)

    # --- Setup ---

    def setup_meanings(self, meanings: list[str]) -> None:
        """设置含义空间。"""
        self._meanings = list(meanings)
        # 同步到笔记本
        self._notebook.write("game:meanings", ",".join(meanings))

    def setup_signals(self, signals: list[str]) -> None:
        """设置信号空间。"""
        self._signals = list(signals)
        self._notebook.write("game:signals", ",".join(signals))

    def setup_agent(self, name: str, exploration_rate: float | None = None,
                    is_sender: bool = True) -> None:
        """配置一个新的智能体替换默认角色。"""
        er = exploration_rate if exploration_rate is not None else 0.1
        agent = SignalingAgent(name, self._notebook, er)
        if is_sender:
            self._sender = agent
        else:
            self._receiver = agent

    # --- Core game loop ---

    def play_round(self, meaning: str | None = None,
                   force_signal: str | None = None) -> dict:
        """执行一轮 signaling game。

        Args:
            meaning: 发送者看到的含义（随机选择如果为 None）
            force_signal: 强制使用的信号（用于测试/干扰）

        Returns:
            包含 round, meaning, signal, interpretation, success 等信息的字典
        """
        # 1. 选择含义
        if meaning is None:
            if not self._meanings:
                return {"error": "No meanings configured"}
            meaning = random.choice(self._meanings)

        # 2. Sender 编码含义为信号
        signal = self._sender.encode(meaning, self._signals)

        if force_signal is not None:
            signal = force_signal

        # 3. Receiver 解码信号为含义
        interpretation = self._receiver.decode(signal)

        # 4. 判断协调是否成功
        success = (interpretation == meaning)

        # 5. 如果是第一次见到这个信号，receiver 学习映射
        if interpretation is None:
            self._receiver.learn_mapping(signal, meaning)
            interpretation = meaning
            success = True

        # 6. 记录交互
        self._sender.record_interaction("sender", meaning, signal,
                                         interpretation, success)
        self._receiver.record_interaction("receiver", meaning, signal,
                                           interpretation, success)

        self._total_rounds += 1
        if success:
            self._successful_rounds += 1
        self._meaning_success[meaning].append(success)

        # 7. 记录轮次
        round_record = {
            "round": self._total_rounds,
            "meaning": meaning,
            "signal": signal,
            "interpretation": interpretation,
            "success": success,
            "ts": time.time(),
        }
        self._round_history.append(round_record)

        # 同步到笔记本
        self._notebook.write(f"round:{self._total_rounds}:result",
                             f"{meaning}->{signal}->{interpretation}:{success}")

        logger.debug(
            "Round %d: meaning=%r signal=%r interpretation=%r success=%r",
            self._total_rounds, meaning, signal, interpretation, success,
        )

        return round_record

    # --- Metrics ---

    @property
    def coordination_rate(self) -> float:
        """整体协调率：成功轮次 / 总轮次。"""
        if self._total_rounds == 0:
            return 0.0
        return self._successful_rounds / self._total_rounds

    def get_coordination_rate_per_meaning(self) -> dict[str, float]:
        """返回每个含义的协调率。"""
        rates = {}
        for meaning, outcomes in self._meaning_success.items():
            if outcomes:
                rates[meaning] = sum(outcomes) / len(outcomes)
            else:
                rates[meaning] = 0.0
        return rates

    def get_entropy(self) -> float:
        """计算信号分布的信息熵（衡量通信渠道的多样性）。

        高熵 = 信号分布均匀（多样化通信）
        低熵 = 信号集中于少数选择（可能过于简化的通信）
        """
        if not self._signals or not self._round_history:
            return 0.0

        signal_counts: dict[str, int] = {s: 0 for s in self._signals}
        for record in self._round_history:
            sig = record.get("signal", "")
            if sig in signal_counts:
                signal_counts[sig] += 1

        total = sum(signal_counts.values())
        if total == 0:
            return 0.0

        entropy = 0.0
        for count in signal_counts.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)

        return entropy

    def get_established_mappings(self) -> dict[str, str]:
        """返回已建立的 meaning → signal 映射。"""
        return self._sender.get_sender_table()

    def get_decoding_mappings(self) -> dict[str, str]:
        """返回已建立的 signal → meaning 解码映射。"""
        return self._receiver.get_receiver_table()

    def ambiguity_score(self) -> float:
        """计算通信的模糊度（0 = 完全清晰，1 = 完全模糊）。

        当多个含义映射到同一个信号时，模糊度增加。
        """
        sender_table = self._sender.get_sender_table()
        if not sender_table:
            return 1.0

        # 统计每个信号被多少含义使用
        signal_to_meanings: dict[str, list[str]] = defaultdict(list)
        for meaning, signal in sender_table.items():
            signal_to_meanings[signal].append(meaning)

        if not signal_to_meanings:
            return 1.0

        # 模糊度 = 平均每个信号对应的含义数 / 总含义数
        avg_meanings_per_signal = sum(
            len(m) for m in signal_to_meanings.values()
        ) / len(signal_to_meanings)

        max_possible = len(self._meanings) if self._meanings else 1
        return min(avg_meanings_per_signal / max_possible, 1.0)

    def play_episode(self, num_rounds: int = 100,
                     report_interval: int = 20) -> dict:
        """执行一个完整 episode 的训练。

        Args:
            num_rounds: 轮次数
            report_interval: 每隔多少轮报告一次进度

        Returns:
            包含 episode 统计的字典
        """
        start_time = time.time()

        for r in range(1, num_rounds + 1):
            self.play_round()

            if r % report_interval == 0:
                logger.info(
                    "Episode round %d/%d — coordination rate: %.3f",
                    r, num_rounds, self.coordination_rate,
                )

        duration = time.time() - start_time

        mappings = self.get_established_mappings()
        decoding = self.get_decoding_mappings()

        return {
            "total_rounds": num_rounds,
            "coordination_rate": self.coordination_rate,
            "successful_rounds": self._successful_rounds,
            "entropy": self.get_entropy(),
            "ambiguity": self.ambiguity_score(),
            "shared_meanings": len(mappings),
            "shared_signals": len(decoding),
            "sender_success_rate": self._sender.get_success_rate(),
            "receiver_success_rate": self._receiver.get_success_rate(),
            "duration_seconds": round(duration, 3),
        }

    # --- Interrogation ---

    def get_sender(self) -> SignalingAgent:
        """返回 sender 智能体引用。"""
        return self._sender

    def get_receiver(self) -> SignalingAgent:
        """返回 receiver 智能体引用。"""
        return self._receiver

    def get_notebook(self) -> ExternalNotebook:
        """返回底层笔记本。"""
        return self._notebook

    def get_round_history(self, limit: int = 50) -> list[dict]:
        """返回最近的 round 历史。"""
        return self._round_history[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """返回 game 的完整统计。"""
        return {
            "total_rounds": self._total_rounds,
            "successful_rounds": self._successful_rounds,
            "coordination_rate": self.coordination_rate,
            "num_meanings": len(self._meanings),
            "num_signals": len(self._signals),
            "entropy": self.get_entropy(),
            "ambiguity_score": self.ambiguity_score(),
            "established_mappings": len(self.get_established_mappings()),
            "decoding_mappings": len(self.get_decoding_mappings()),
            "sender": self._sender.get_stats(),
            "receiver": self._receiver.get_stats(),
            "notebook": self._notebook.get_stats(),
        }
