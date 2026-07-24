"""omega 包 — 心跳后台线程逻辑外置.

真拆 life.py 第二步(最高收益高风险项, 用户授权):
把 Omega._heartbeat_loop(990-1017) 纯搬迁到 run_heartbeat(omega)。
心跳是独立的 daemon 线程逻辑, 与主循环调度解耦, 可外置收敛上帝类。

纯搬迁, 行为逐行不变: 每 _heartbeat_interval 秒触发 learn, CNS 链自动
reflect → evolve → dream → maintain; 仅记录成功/失败, 不阻塞主循环。
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


def run_heartbeat(self) -> None:
    """心跳 daemon 循环(原 Omega._heartbeat_loop 的纯搬迁版本).

    Args:
        self: Omega 实例(读 _heartbeat_running / _hb_sources / _hb_src_i, 调 .learn)
    """
    while self._heartbeat_running:
        try:
            time.sleep(self._heartbeat_interval)

            if not self._heartbeat_running:
                break
            # 触发 learn，CNS 会链式触发剩余管道

            hb_query = "auto heartbeat"
            if getattr(self, "focus_topics", None):
                top = self.focus_topics.most_common(1)
                if top:
                    hb_query = top[0][0]
            # 源轮转: 每轮心跳换一个源, 让论文(arxiv)/代码(github)/百科(wiki)节点自动积累
            hb_src = self._hb_sources[self._hb_src_i % len(self._hb_sources)]
            self._hb_src_i += 1
            result = self.learn(source=hb_src, query=hb_query, max_results=1)
            # 只记录成功/失败，不阻塞主循环
            if result.get("success") or result.get("new_nodes", 0) > 0:
                logger.info("Heartbeat: learn OK (%d nodes)", result.get("new_nodes", 0))
            else:
                logger.warning("Heartbeat: learn returned %s", result.get("reason", "unknown"))
        except Exception as e:
            logger.warning("Heartbeat cycle failed: %s", e)
