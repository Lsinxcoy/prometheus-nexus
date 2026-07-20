"""EvolutionState — T1 进化状态跨会话持久化。

解决: EvolutionEngine 的 gene_specs / 最佳染色体进程内, 重启即丢,
导致进化无累积(每次从零)。本模块把状态序列化到本地 JSON 文件
(进化状态是全局配置, 非知识节点, 用文件比污染 store 更干净)。

Crash-safety contract (cycle 17 hardening, 沿用 cycle15 StatePersistence 约定):
  * save() 原子写(临时文件 -> os.replace)并 fsync, 崩溃中途写永不留下半截主文件。
  * save() 覆盖前先把上一版完好状态复制为 .bak, 主文件损坏也能从最近一次完整写恢复。
  * 保存/加载失败一律 logger.warning(而非 DEBUG)暴露 —— 进化进度丢失是生产可见事件,
    绝不能在默认日志级别下静默消失。
  * load() 区分"无状态文件(首跑 benign -> False, 不告警)"与"文件损坏(loud -> WARNING 并回退 .bak)"。
"""
from __future__ import annotations

import json
import logging
import os
import shutil

logger = logging.getLogger(__name__)

STATE_KEY = "evo_state:v1"
DEFAULT_PATH = "archive/evo_state.json"


class EvolutionState:
    """进化状态存取(文件持久化)。"""

    def __init__(self, store=None, path: str = DEFAULT_PATH):
        self.store = store
        self.path = path
        self._bak_path = path + ".bak"
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)

    def save(self, engine) -> bool:
        """保存进化引擎状态(gene_specs + 代数)。

        原子写 + 备分 + 失败 WARNING。返回 True 写入成功, False 失败
        (失败已记 WARNING, 调用方据此判断 chain_trace, 而非静默当成功)。
        """
        try:
            specs = getattr(engine, "_gene_specs", {}) or {}
            state = {
                "gene_specs": {k: list(v) for k, v in specs.items()},
                "generation": getattr(engine, "_generation", 0),
            }
            # 覆盖前先把上一版完好状态备分为 .bak(永远是上次完整写, 非半截)。
            if os.path.exists(self.path):
                try:
                    shutil.copyfile(self.path, self._bak_path)
                except OSError as e:
                    logger.warning("EvolutionState: 无法备分上一版状态: %s", e)
            # 原子写: 同目录临时文件 -> fsync -> os.replace(原子重命名 POSIX & Win)。
            # 崩溃发生在 os.replace 之前只留下孤立临时文件, 主文件永远完好。
            tmp_path = self.path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
            return True
        except Exception as e:
            logger.warning(
                "EvolutionState.save 失败(进化状态未持久化, 重启将丢失进度): %s", e
            )
            # 清理可能半截的临时文件; 不动现有主文件/.bak, 保证可恢复。
            try:
                tmp = self.path + ".tmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return False

    def load(self, engine) -> bool:
        """恢复进化引擎状态。

        损坏回退 .bak, 失败 WARNING 并返 False(绝不静默吞)。
        返回 True 恢复成功, False 无文件(首跑 benign)或恢复失败。
        """
        # 首跑: 无状态文件, benign, 不告警。
        if not os.path.exists(self.path):
            return False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            # 主文件损坏: 先试 .bak 回退。
            logger.warning("EvolutionState.load 主文件损坏, 尝试 .bak 回退: %s", e)
            return self._load_from_bak(engine)
        return self._apply(engine, state)

    def _load_from_bak(self, engine) -> bool:
        if not os.path.exists(self._bak_path):
            logger.warning("EvolutionState.load: 主备均不可用, 进化状态丢失(首跑式空启动)")
            return False
        try:
            with open(self._bak_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            logger.warning("EvolutionState.load: 已从 .bak 恢复进化状态")
            return self._apply(engine, state)
        except Exception as e:
            logger.warning("EvolutionState.load: .bak 亦损坏, 进化状态丢失: %s", e)
            return False

    @staticmethod
    def _apply(engine, state) -> bool:
        try:
            specs = {k: tuple(v) for k, v in state.get("gene_specs", {}).items()}
            if specs:
                engine._gene_specs = specs
            if "generation" in state:
                engine._generation = state["generation"]
            return True
        except Exception as e:
            logger.warning("EvolutionState.load: 状态结构非法, 恢复失败: %s", e)
            return False
