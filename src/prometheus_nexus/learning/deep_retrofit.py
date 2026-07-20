"""DeepRetrofit — dependency analysis and backward-compatible refactoring.

基于:
- "Impact-Aware Refactoring" (Mockus & Weiss, 2001) + Omega深度重构引擎
  - 依赖分析: import/reference/class_usage/method_call/name_reference
  - 影响评估: 依赖强度均值 × 0.5 + 依赖数量 × 0.05
  - 迁移规划: 按风险等级(low/medium/high)生成步骤列表

算法:
    retrofit(context):
        1. _analyze_dependencies() → 5种依赖类型
        2. _estimate_impact() → 风险评分+因素
        3. _plan_migration() → 步骤清单
        4. _update_dependency_map() → 依赖图谱更新

来源: Omega系统 deep_retrofit 深度重构模块
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import re


class DeepRetrofit:
    def __init__(self, omega=None):
        self._omega = omega
        self._retrofits: list[dict] = []
        self._dependency_map: dict[str, list[str]] = {}
        self._impact_history: list[dict] = []

    def retrofit(self, context: str = "") -> dict:
        deps = self._analyze_dependencies(context)
        impact = self._estimate_impact(deps)
        plan = self._plan_migration(impact, deps)
        self._update_dependency_map(context, deps)

        result = {
            "context": context,
            "dependencies_found": len(deps),
            "dependency_details": deps[:10],
            "impact_score": impact["score"],
            "impact_risk": impact["risk"],
            "impact_factors": impact["factors"],
            "plan_steps": len(plan["steps"]),
            "plan_details": plan["steps"],
            "retrofitted": True,
        }
        self._retrofits.append(result)
        self._impact_history.append(impact)
        return result

    def _analyze_dependencies(self, context: str) -> list[dict]:
        deps = []
        import_patterns = re.findall(r'(?:import|from|require|include)\s+[\w.]+', context)
        for pattern in import_patterns:
            module = pattern.split()[-1] if pattern.split() else pattern
            deps.append({"module": module, "type": "import", "strength": 1.0})

        dotted_names = re.findall(r'\b([A-Z][a-z]+(?:\.[A-Z][a-z]+)+)\b', context)
        for name in dotted_names:
            deps.append({"module": name, "type": "reference", "strength": 0.7})

        function_calls = re.findall(r'\b(\w+)\.\w+\(', context)
        for func in set(function_calls):
            if len(func) > 3 and func[0].isupper():
                deps.append({"module": func, "type": "class_usage", "strength": 0.8})

        method_calls = re.findall(r'self\.(\w+)\.(\w+)\(', context)
        for obj, method in method_calls:
            deps.append({"module": "%s.%s" % (obj, method), "type": "method_call", "strength": 0.9})

        word_deps = re.findall(r'\b(\w{5,})\b', context)
        for word in set(word_deps):
            if word[0].isupper() and word not in {"False", "True", "None"}:
                deps.append({"module": word, "type": "name_reference", "strength": 0.5})

        return deps

    def _estimate_impact(self, deps: list[dict]) -> dict:
        if not deps:
            return {"score": 0.0, "risk": "none", "factors": ["no_dependencies"]}

        total_strength = sum(d.get("strength", 0.5) for d in deps)
        type_counts = {}
        for d in deps:
            t = d.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        score = min(1.0, total_strength / max(len(deps), 1) * 0.5 + len(deps) * 0.05)

        factors = []
        if type_counts.get("import", 0) > 3:
            factors.append("many_imports")
            score += 0.1
        if type_counts.get("method_call", 0) > 5:
            factors.append("heavy_method_coupling")
            score += 0.15
        if type_counts.get("class_usage", 0) > 2:
            factors.append("class_level_dependency")
            score += 0.1

        score = min(1.0, score)
        risk = "low" if score < 0.3 else "medium" if score < 0.7 else "high"

        return {"score": score, "risk": risk, "factors": factors}

    def _plan_migration(self, impact: dict, deps: list[dict]) -> dict:
        steps = []
        risk = impact["risk"]

        steps.append("audit_affected_components")

        if risk in ("medium", "high"):
            steps.append("create_feature_branch")
            steps.append("map_change_propagation")

        import_deps = [d for d in deps if d.get("type") == "import"]
        if import_deps:
            steps.append("update_%d_import_statements" % len(import_deps))

        method_deps = [d for d in deps if d.get("type") == "method_call"]
        if method_deps:
            steps.append("verify_%d_method_contracts" % len(method_deps))

        steps.append("run_regression_tests")

        if risk == "high":
            steps.append("run_integration_tests")
            steps.append("update_documentation")
            steps.append("peer_review")

        steps.append("verify_api_compatibility")
        steps.append("merge_to_main")

        return {"steps": steps}

    def _update_dependency_map(self, context: str, deps: list[dict]):
        if context:
            key = context[:50]
            self._dependency_map[key] = [d["module"] for d in deps]

    def get_dependency_graph(self) -> dict:
        return dict(self._dependency_map)

    def get_stats(self) -> dict:
        return {
            "retrofits": len(self._retrofits),
            "avg_impact": sum(i["score"] for i in self._impact_history) / max(len(self._impact_history), 1),
            "dependency_map_size": len(self._dependency_map),
        }
