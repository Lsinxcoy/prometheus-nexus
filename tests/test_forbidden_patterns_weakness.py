"""ForbiddenPatternDetector 安全盲点修复验证.

弱点: 编译失败的禁区正则被静默丢弃(add_pattern 原 `except re.error: self._compiled[pid]=None`
把规则置空), check() 跳过 None 模式, 而 get_stats()['patterns_count'] 仍计入死规则 -> 虚假覆盖.
该检测器挂在 life.py remember() 安全门(Gate 0.9), 静默漏防直接削弱记忆安全门.

修复后:
  1. add_pattern 对非法正则 raise ValueError(拒绝静默漏防, 调用方必须处理).
  2. __init__ 对默认非法正则记 logger.error(旧代码零日志).
  3. get_stats 新增 effective_patterns 暴露真实生效数(覆盖缺口可见).

反向敏感性: 旧代码下以下测试必失败 ——
  - test_add_pattern_invalid_regex_raises: 旧代码静默返回 None, 无 raise -> 失败.
  - test_get_stats_exposes_effective_count_gap: 旧代码无 effective_patterns 键 -> KeyError 失败; 且旧代码无 error 日志 -> 断言失败.
  - test_init_valid_defaults_all_effective: 旧代码无 effective_patterns 键 -> KeyError 失败.
"""
import logging

import pytest

from prometheus_nexus.memory.forbidden_patterns import ForbiddenPatternDetector

# 注意: ForbiddenPatternDetector(patterns=...) 用 `patterns or DEFAULT_PATTERNS`,
# 传 [] 会被静默替换为默认 8 条规则(这是另一个独立潜在 bug, 本轮不修).
# 为隔离测试 add_pattern, 用一个绝不命中的哨兵种子模式, 动态计算基线计数.
_SEED = [{"id": "seed", "pattern": "zzz_never_match_sentinel_xyz", "severity": "warning", "description": ""}]


def test_add_pattern_invalid_regex_raises_and_not_added():
    d = ForbiddenPatternDetector(patterns=list(_SEED))
    n0 = len(d._patterns)
    with pytest.raises(ValueError):
        d.add_pattern("bad", "(unclosed")
    # 非法规则未被静默加入(既不进 _patterns 也不进 _compiled)
    assert "bad" not in d._compiled
    assert all(p["id"] != "bad" for p in d._patterns)
    assert len(d._patterns) == n0


def test_add_pattern_valid_is_enforced_and_counted():
    d = ForbiddenPatternDetector(patterns=list(_SEED))
    base_eff = d.get_stats()["effective_patterns"]
    d.add_pattern("leak", r"secret_\d+", severity="critical")
    violations = d.check("the secret_42 token leaked")
    assert "leak" in [v["pattern_id"] for v in violations]
    assert d.get_stats()["effective_patterns"] == base_eff + 1


def test_get_stats_exposes_effective_count_gap(caplog):
    # 构造含一个非法默认正则的检测器(走 __init__ 沉默降级 + 记 error 路径)
    bad = {"id": "broken", "pattern": "(unclosed", "severity": "warning", "description": "x"}
    with caplog.at_level(logging.ERROR):
        d = ForbiddenPatternDetector(patterns=[bad])
    stats = d.get_stats()
    assert stats["patterns_count"] == 1        # 声明数
    assert stats["effective_patterns"] == 0     # 真实生效数(缺口可见)
    # 非法默认正则必须显式 error 日志(旧代码零日志)
    assert any("failed to compile" in r.message for r in caplog.records), caplog.text
    # 该模式永不生效: check 不报任何违规 -> 静默漏防被量化暴露
    assert d.check("anything (unclosed bracket") == []


def test_init_valid_defaults_all_effective_no_error_log(caplog):
    with caplog.at_level(logging.ERROR):
        d = ForbiddenPatternDetector()  # 默认全是合法正则
    stats = d.get_stats()
    assert stats["patterns_count"] == stats["effective_patterns"]
    # 合法默认不应产生 error 日志
    assert not any(r.levelno >= logging.ERROR for r in caplog.records), caplog.text


def test_add_pattern_multiple_propagate_to_stats_and_check():
    d = ForbiddenPatternDetector(patterns=list(_SEED))
    d.add_pattern("p1", r"forbidden_word", severity="critical")
    d.add_pattern("p2", r"another_(bad|good)", severity="warning")
    stats = d.get_stats()
    assert stats["patterns_count"] == 1 + 2
    assert stats["effective_patterns"] == 1 + 2
    v = d.check("this has forbidden_word and another_bad here")
    assert {x["pattern_id"] for x in v} == {"p1", "p2"}


def test_check_whitelist_still_skips(caplog):
    # 回归: 白名单行为不受影响
    d = ForbiddenPatternDetector(patterns=[])
    d.add_pattern("p1", r"forbidden_word", severity="critical")
    d.add_to_whitelist("p1")
    assert d.check("has forbidden_word") == []
