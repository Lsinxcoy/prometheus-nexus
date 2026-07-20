"""EDREReplicator.replicate 适应度信号丢失修复回归测试 (cycle 38).

根因: life.py:2492 调用 self.edre.replicate({"context": context, "fitness": fitness_before}),
把真实进化适应度放在 data 字典内; 但 edre.replicate 仅读取关键字参数 fitness
(默认 0.5), 从不读 data["fitness"]。结果 self._fitnesses[context] 恒为 0.5,
EDRE 复制动力学 (选择压力 x_i*(f_i - f_bar)) 每轮收到常量适应度 —— 真实进化
适应度信号被静默丢弃, 均衡分布退化为无差异。该模块由 life.py:526 实例化、
:2492 在每轮 evolve 真实调用 (生产路径)。

修复: replicate 内 fitness = data.get("fitness", fitness), 字典优先、关键字回退。

本测试固化:
  1. data 内 fitness 必须被采用 (直接复现 life.py:2492 的调用风格, 修复前为 0.5)
  2. 关键字参数 fitness 风格仍生效 (文档示例)
  3. 默认 fitness 回退仍为 0.5
  4. 真实适应度差异必须驱动选择压力 (高 fitness 占比 > 低 fitness 占比;
     修复前两者恒等, 选择压力无差异)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.ecosystem.edre import EDREReplicator


def test_dict_fitness_is_honored():
    """life.py:2492 风格: fitness 在 data 字典内 -> 必须被采用 (修复前恒为 0.5)。"""
    edre = EDREReplicator()
    edre.replicate({"context": "evolve_ctx", "fitness": 0.92})
    assert edre._fitnesses["evolve_ctx"] == 0.92


def test_kwarg_fitness_still_works():
    """文档示例风格: fitness 作关键字参数 -> 仍生效。"""
    edre = EDREReplicator()
    edre.replicate({"context": "coding"}, fitness=0.8)
    assert edre._fitnesses["coding"] == 0.8


def test_default_fitness_fallback():
    """两者都不给 -> 回退默认 0.5。"""
    edre = EDREReplicator()
    edre.replicate({"context": "default_ctx"})
    assert edre._fitnesses["default_ctx"] == 0.5


def test_fitness_signal_drives_selection_pressure():
    """真实适应度差异必须驱动选择压力: 高 fitness 占比 > 低 fitness 占比。

    使用 life.py:2492 的字典内 fitness 风格 —— 修复前两个上下文都收到常量 0.5,
    选择压力无差异, 占比恒等, 本断言失败; 修复后 0.95/0.05 驱动高者占比更高。
    """
    edre = EDREReplicator()
    for _ in range(15):
        edre.replicate({"context": "high", "fitness": 0.95})
        edre.replicate({"context": "low", "fitness": 0.05})
    shares = edre.get_shares()
    assert shares["high"] > shares["low"]
