"""类型边界测试: OutputGuardrail.check 必须容忍非 str 内容 (None/dict/int).

背景: OutputGuardrail 是 Omega 生产输出安全门 (life.py:504 实例化,
life.py:1658/1757 对记忆召回 content 调用)。其 sibling InputGuardrail
已在 guardrail.py:82 对非 str 内容做 `content = str(content)` 防御,
唯独 OutputGuardrail.check 缺少该防御: `len(content)` / `re.search(pat, content)` /
`content[:1000]` 在 content 为 None/dict/int 时抛 TypeError, 使安全门自身崩溃,
进而拖垮调用方 (recall/remember) 整条管线 —— 真实类型边界薄弱 (安全门静默失效,
fail-open / 崩溃扩散)。content 为 None 在记忆节点 content 字段为 null、
结构化 dict/list 输出时真实可达。

修复: OutputGuardrail.check 入参处增加与 InputGuardrail 一致的
`if not isinstance(content, str): content = str(content)` 防御。

测试策略: 用 None/dict/int 三种非 str 输入断言不崩溃且返回 GuardrailResult;
用含毒性短语的 dict 断言 coerce 后仍检出 toxicity (证明修复既防崩又保功能, 非退化)。
先以 buggy 代码跑验证 None/dict/int 用例确抛 TypeError (非假绿)。

注意: OutputGuardrail 仅校验 _TOXIC_PATTERNS(毒性)/长度/控制字符,
不校验 injection/sensitive (那是 InputGuardrail 的职责), 故回归用例只验证
其自身真实契约 (毒性字符串仍被检出)。
"""
import sys

sys.path.insert(0, "src")

from prometheus_nexus.harness.guardrail import OutputGuardrail, GuardrailResult


def test_output_guardrail_none_does_not_crash():
    g = OutputGuardrail()
    # None content (记忆节点 content 为 null 的真实场景) 不应使安全门崩溃
    r = g.check(None)
    assert isinstance(r, GuardrailResult)
    # str(None) == "None" 不含任何毒性模式 -> 通过
    assert r.passed is True


def test_output_guardrail_dict_coerced_and_detects_toxicity():
    g = OutputGuardrail()
    # 结构化 dict 输出: coerce 为 str 后毒性短语仍应被检出
    # (修复既防崩又保功能, 而非简单吞错退化)
    r = g.check({"text": "go to hell"})
    assert isinstance(r, GuardrailResult)
    assert "toxicity" in r.violations
    assert r.passed is False


def test_output_guardrail_int_does_not_crash():
    g = OutputGuardrail()
    r = g.check(123)
    assert isinstance(r, GuardrailResult)


def test_output_guardrail_toxic_string_still_detected():
    g = OutputGuardrail()
    # 回归: 修复后 OutputGuardrail 自身真实契约 (毒性字符串) 仍被正确拦截
    r = g.check("you must kill him now")
    assert isinstance(r, GuardrailResult)
    assert "toxicity" in r.violations
    assert r.passed is False
