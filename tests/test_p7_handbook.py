"""P7 Harness Handbook 行为定位层测试.

验证 Harness Handbook (arXiv:2607.13285) 移植进 ULTRA 的三方向:
- 方向1: 行为定位 (behavior -> source location)
- 方向2: BGPD 三级渐进披露 (省 token, 更准定位)
- 方向3: 自映射 (对 ULTRA 自身代码库建 handbook)

以及 T4 接线: compile() 产物带 target_location, 无 LLM 时优雅降级(规则定位非空).
"""
import sys
sys.path.insert(0, "E:/Prometheus-Ultra-MultiTypeKB/src")

import pytest


SAMPLE_SRC = '''
"""sample module for handbook test."""
from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism


class EvolutionEngine:
    """参数进化引擎: 管理基因选择与适应度评估."""

    def evolve(self, generations=10):
        """执行进化循环, 返回最优个体."""
        return None

    def _selection(self, pop):
        """选择算子: 基于适应度挑选父代."""
        return pop


def learn_external(url: str):
    """吸收外部知识, 路由到对应轨道."""
    return url
'''


class TestHandbookBuild:
    def test_build_from_src_tree(self):
        """方向3: 对 ULTRA 代码库建 handbook, 提取行为条目。"""
        from prometheus_nexus.mechanisms.handbook import HarnessHandbook
        # 用真实 src 根(懒构建会扫全部, 较慢但真实)
        hb = HarnessHandbook()
        entries = hb.build()
        assert len(entries) > 50, "handbook 应提取大量行为条目"
        # 应含关键行为(如 T4 compiler 的 compile)
        sigs = [e.signature for e in entries]
        assert any("compile(" in s for s in sigs), "应含 compile() 行为"

    def test_build_from_string(self, tmp_path):
        """用临时源码树验证 AST 提取逻辑(快速, 不扫全库)。"""
        from prometheus_nexus.mechanisms.handbook import HarnessHandbook
        mod_dir = tmp_path / "pkg"
        mod_dir.mkdir()
        (mod_dir / "__init__.py").write_text("")
        (mod_dir / "sample.py").write_text(SAMPLE_SRC)
        hb = HarnessHandbook(str(tmp_path))
        entries = hb.build(str(tmp_path))
        sigs = [e.signature for e in entries]
        assert "evolve(generations)" in sigs, "应提取 EvolutionEngine.evolve"
        assert "learn_external(url)" in sigs, "应提取模块级函数"
        # 行为描述来自 docstring
        evo = [e for e in entries if e.signature == "evolve(generations)"][0]
        assert "进化" in evo.behavior, "行为描述应来自 docstring"


class TestBehaviorLocalization:
    def test_rule_locate_no_llm(self, tmp_path):
        """方向1 降级: 无 LLM 时关键词规则定位给出非空候选。"""
        from prometheus_nexus.mechanisms.handbook import HarnessHandbook
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "sample.py").write_text(SAMPLE_SRC)
        hb = HarnessHandbook(str(tmp_path))
        hb.build(str(tmp_path))
        # 查询含 "进化" 应命中 EvolutionEngine.evolve
        cands = hb.locate_behavior("参数进化 适应度", llm=None, top_k=1)
        assert len(cands) >= 1, "无 LLM 时应仍能关键词定位"
        assert cands[0].verified is True, "候选位置应对照 handbook 验证存在"
        # 命中进化相关行为(类 EvolutionEngine 或方法 evolve 均含 'evo')
        assert "evo" in cands[0].symbol.lower(), "应定位到进化相关行为"

    def test_llm_locate_uses_llm(self, tmp_path):
        """方向1: 有 LLM 时调用 LLM 定位(解析返回格式)。"""
        from prometheus_nexus.mechanisms.handbook import HarnessHandbook
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "sample.py").write_text(SAMPLE_SRC)
        hb = HarnessHandbook(str(tmp_path))
        hb.build(str(tmp_path))

        class FakeLLM:
            available = True
            def complete(self, prompt, system=""):
                # 模拟 LLM 返回 MODULE|LINENO|SYMBOL|CONFIDENCE|RATIONALE
                # module 用 'sample' 匹配 handbook 实际 module 名(临时树无包前缀)
                return "sample|6|evolve(generations)|0.9|匹配参数进化行为"
        cands = hb.locate_behavior("参数进化", llm=FakeLLM(), top_k=1)
        assert len(cands) == 1
        assert cands[0].module == "sample"
        assert cands[0].symbol == "evolve(generations)"
        assert cands[0].confidence == 0.9
        assert cands[0].verified is True


class TestBGPD:
    def test_bgpd_locate(self, tmp_path):
        """方向2: BGPD 三级渐进定位, 返回 Level3 已验证候选。"""
        from prometheus_nexus.mechanisms.handbook import HarnessHandbook
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "sample.py").write_text(SAMPLE_SRC)
        hb = HarnessHandbook(str(tmp_path))
        hb.build(str(tmp_path))
        cands = hb.bgpd_locate("外部知识吸收与路由", llm=None, top_k=1)
        assert len(cands) >= 1
        assert cands[0].level == 3, "BGPD 应返回 Level3 具体函数"
        assert cands[0].verified is True
        assert "learn_external" in cands[0].symbol, "应定位到 learn_external 行为"


class TestT4Integration:
    def test_compile_attaches_target_location(self, tmp_path, monkeypatch):
        """T4 compile() 产物带 target_location (P7 接线)。"""
        from prometheus_nexus.mechanisms.mechanism_compiler import MechanismCompiler
        from prometheus_nexus.mechanisms.source_fetcher import fetch_arxiv_fulltext

        # mock 全文获取(不联网)
        monkeypatch.setattr(
            "prometheus_nexus.mechanisms.mechanism_compiler.fetch_arxiv_fulltext",
            lambda aid: "We propose a novel parameter evolution method that improves fitness adaptation.",
        )
        # mock handbook 定位(避免扫全库)
        from prometheus_nexus.mechanisms import handbook as hb_mod
        class FakeCand:
            module = "prometheus_nexus.evolution.evolution_engine"
            filepath = "/x/evolution_engine.py"
            lineno = 2357
            symbol = "evolve()"
            confidence = 0.8
            verified = True
            rationale = "匹配参数进化行为"
            level = 3
        monkeypatch.setattr(hb_mod.HarnessHandbook, "bgpd_locate",
                            lambda self, q, llm, top_k: [FakeCand()])
        monkeypatch.setattr(hb_mod.HarnessHandbook, "locate_behavior",
                            lambda self, q, llm, top_k: [FakeCand()])

        comp = MechanismCompiler(llm=None, compiled_dir=str(tmp_path / "compiled"))
        mech = comp.compile("2401.12345", "Test Paper")
        assert mech is not None
        assert mech.target_location, "compile 产物应带 target_location"
        assert mech.target_location["module"] == "prometheus_nexus.evolution.evolution_engine"
        assert mech.target_location["lineno"] == 2357
        assert mech.target_location["verified"] is True

    def test_compile_graceful_when_handbook_empty(self, tmp_path, monkeypatch):
        """handbook 定位失败时 compile 仍返回机制(target_location 为空 dict, 不崩)。"""
        from prometheus_nexus.mechanisms.mechanism_compiler import MechanismCompiler
        monkeypatch.setattr(
            "prometheus_nexus.mechanisms.mechanism_compiler.fetch_arxiv_fulltext",
            lambda aid: "We propose a method for memory consolidation.",
        )
        from prometheus_nexus.mechanisms import handbook as hb_mod
        monkeypatch.setattr(hb_mod.HarnessHandbook, "bgpd_locate",
                            lambda self, q, llm, top_k: [])
        monkeypatch.setattr(hb_mod.HarnessHandbook, "locate_behavior",
                            lambda self, q, llm, top_k: [])

        comp = MechanismCompiler(llm=None, compiled_dir=str(tmp_path / "compiled"))
        mech = comp.compile("2401.99999", "Paper2")
        assert mech is not None
        assert mech.target_location == {}, "定位失败时 target_location 应为空 dict(不崩)"
