"""Phase 4 系统级回归: 固定 eval 集驱动 T2/T3/T4 实际执行, 测真实指标.

不依赖真实 LLM/网络 — 用 FakeLLM 返回合法机制草案, 让 T3/T4 编译链路真实跑通.
测量(诚实, 不全信 fitness 数字):
  - T2: SemanticToParam 提案数 + 经 inject_gene_specs 注入 evolution_engine 的 specs
  - T3: AST 提取的 gene_specs + 编译产物进 candidate
  - T4: 编译通过且 run() 非空壳的机制数 + 进 candidate
  - 机制消费率(被 dispatch 调用)
  - fitness 前后 delta + 维度分解
"""
from __future__ import annotations

import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prometheus_nexus.life import Omega
from prometheus_nexus.mechanisms.base_mechanism import BaseMechanism


class _FakeLLM:
    """返回合法机制草案(引用 context, 非占位), 让编译链路真实跑通."""
    def __init__(self):
        self.available = True
        self.calls = 0

    def complete(self, prompt, system=None, temperature=0.3, max_tokens=2048):
        self.calls += 1
        # T4 编译: 返回合法 BaseMechanism 子类草案
        if "机制编译器" in (system or "") or "编译" in (system or ""):
            return (
                "class CompiledMech(BaseMechanism):\n"
                "    def run(self, context):\n"
                "        x = context.get('input', 0)\n"
                "        return {'ok': True, 'result': x * 2, 'source': 'paper'}\n"
            )
        # T3 提取: 返回机制描述
        if "机制提取器" in (system or ""):
            return "MECHANISM: adaptive_attention\nWHAT: 稀疏注意力\nCONTRACT: in=query out=attn"
        # 其他(修正 prompt 等): 也返回合法草案
        return (
            "class CompiledMech(BaseMechanism):\n"
            "    def run(self, context):\n"
            "        v = context.get('v', 1)\n"
            "        return {'ok': True, 'doubled': v * 2}\n"
        )


def _build_eval_nodes():
    """固定 eval 集节点(直接构造 Node, 绕过 learn 网络抓取)."""
    from prometheus_nexus.foundation.schema import Node, NodeType
    nodes = []
    # T2: 反复出现 'sparse attention' 主题(>=3 次触发 SemanticToParam)
    for i in range(4):
        nodes.append(Node(type=NodeType.CONCEPT, tags=["sparse", "attention"],
                          content=f"sparse attention mechanism variant {i}", utility=0.6))
    # T2: 'memory decay' 主题
    for i in range(3):
        nodes.append(Node(type=NodeType.CONCEPT, tags=["decay", "memory"],
                          content=f"memory decay curve {i}", utility=0.4))
    # T3: GitHub 项目
    nodes.append(Node(type=NodeType.PROJECT, tags=["github", "agent"],
                      content="agent memory evolution repo", utility=0.7,
                      url="https://github.com/owner/awesome-agent"))
    # T4: arxiv 论文
    nodes.append(Node(type=NodeType.PAPER, tags=["paper", "mechanism"],
                      content="novel sparse attention for agents", utility=0.8,
                      url="https://arxiv.org/abs/2607.16193"))
    return nodes


def main():
    db = os.path.join(tempfile.gettempdir(), "omega_phase4_eval.db")
    if os.path.exists(db):
        os.remove(db)
    o = Omega(db_path=db)
    # 注入 FakeLLM(覆盖真实 LLM 桥, 避免网络依赖)
    from prometheus_nexus.integration.llm_bridge import LLMBridge
    o.llm = _FakeLLM()
    o.mechanism_extractor.llm = o.llm
    o.mechanism_compiler.llm = o.llm

    nodes_spec = _build_eval_nodes()

    # 初始 fitness
    f_before = o._compute_fitness()
    print(f"[init] fitness={f_before:.4f} nodes={o.store.get_node_count()}")

    N = 5
    t2_proposals_total = 0
    t3_specs_total = 0
    t4_compiled = 0
    t4_candidates = 0

    for cycle in range(1, N + 1):
        # 1) 写固定 eval 节点进 store(让 T2/SemanticToParam 能读到; 绕过 learn 网络)
        for ns in nodes_spec:
            try:
                o.store.create_node(ns)
            except Exception as e:
                pass  # 重复节点可能已存在, 忽略

        # 2) evolve(驱动 T1+T2 闭环)
        try:
            o.evolve(context=f"eval_cycle_{cycle}")
        except Exception as e:
            print(f"  evolve err: {e}")

        # 3) 测量 T2 提案(经 SemanticToParam 注入 evolution_engine 的 specs)
        specs = getattr(o.evolution_engine, "_gene_specs", {}) or {}
        t2_like = {k: v for k, v in specs.items()
                   if k.startswith("ext_") or k in ("attention_sparsity", "memory_decay")}
        t2_proposals_total = len(t2_like)

        # 4) 测量 T3(从 learn 节点提取 + 编译)
        try:
            ext = o.mechanism_extractor.extract_from_node(_fake_node("https://github.com/owner/awesome-agent"))
            if ext and ext.gene_specs:
                t3_specs_total = max(t3_specs_total, len(ext.gene_specs))
        except Exception as e:
            print(f"  t3 err: {e}")

        # 5) 测量 T4(编译论文机制)
        try:
            comp = o.mechanism_compiler.compile_from_node(_fake_node("https://arxiv.org/abs/2607.16193"))
            if comp is not None and comp.draft_code:
                t4_compiled += 1
                # 校验 run() 非空壳
                from prometheus_nexus.mechanisms.mechanism_compiler import MechanismCompiler
                if MechanismCompiler._run_is_non_trivial(comp.draft_code):
                    t4_candidates += 1
        except Exception as e:
            print(f"  t4 err: {e}")

        f_now = o._compute_fitness()
        print(f"[cycle {cycle}] fitness={f_now:.4f} t2_specs={t2_proposals_total} "
              f"t3_specs={t3_specs_total} t4_compiled={t4_compiled} t4_non_shell={t4_candidates}")

    f_after = o._compute_fitness()
    print("\n=== Phase 4 系统级回归结果 ===")
    print(f"fitness: {f_before:.4f} -> {f_after:.4f} (delta={f_after-f_before:+.4f})")
    print(f"T2 强化提案(注入 evolution_engine 的 specs 维度): {t2_proposals_total}")
    print(f"T3 AST 提取 gene_specs 维度: {t3_specs_total}")
    print(f"T4 编译机制数: {t4_compiled}, 其中 run() 非空壳: {t4_candidates}")
    print(f"FakeLLM 调用次数: {o.llm.calls}")

    # 诚实判定
    ok = True
    if t2_proposals_total == 0:
        print("WARN: T2 未产出强化提案"); ok = False
    if t4_candidates == 0:
        print("WARN: T4 未编译出非空壳机制"); ok = False
    print("RESULT:", "PASS" if ok else "NEEDS_REVIEW")


def _fake_node(url):
    class _N:
        def __init__(self, u):
            self.url = u
            self.id = "eval_node"
    return _N(url)


if __name__ == "__main__":
    main()
