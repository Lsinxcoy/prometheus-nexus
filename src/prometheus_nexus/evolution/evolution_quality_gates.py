"""EvolutionQualityGates — 进化质量门禁系统.

基于:
- "Quality Gates in Software Engineering" (ISO/IEC 25010)
  - 功能性: 功能正确性
  - 性能: 效率指标
  - 可靠性: 稳定性指标
  - 可维护性: 代码质量

Note: This module implements quality gates for evolution results using the
ISO/IEC 25010 quality framework. It has NO specific arXiv paper dependency.
The five gates (functional, performance, reliability, diversity, convergence)
are a project-specific adaptation of standard software quality metrics to the
evolutionary computation domain.

算法:
    check(evolution_result):
        1. 功能检查: 输出是否有效
        2. 性能检查: 适应度提升是否足够
        3. 可靠性检查: 变异率是否在安全范围
        4. 多样性检查: 种群多样性
        5. 收敛性检查: 是否过度拟合
        6. 综合决策: 通过/警告/拒绝

复杂度:
    check(): O(G) 其中 G = 门禁数量
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


import time
from dataclasses import dataclass, field
from enum import Enum


class GateResult(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class GateCheck:
    """单个门禁检查结果."""
    name: str = ""
    result: GateResult = GateResult.PASS
    score: float = 0.0
    message: str = ""


@dataclass
class QualityReport:
    """质量报告."""
    overall: GateResult = GateResult.PASS
    checks: list[GateCheck] = field(default_factory=list)
    timestamp: float = 0.0
    
    @property
    def pass_rate(self) -> float:
        if not self.checks:
            return 1.0
        return sum(1 for c in self.checks if c.result == GateResult.PASS) / len(self.checks)
    
    @property
    def avg_score(self) -> float:
        if not self.checks:
            return 0.0
        return sum(c.score for c in self.checks) / len(self.checks)


class EvolutionQualityGates:
    """进化质量门禁系统.
    
    五道门禁确保进化质量.
    """
    
    def __init__(self, fitness_threshold: float = 0.3, max_mutation_rate: float = 0.5):
        self.fitness_threshold = fitness_threshold
        self.max_mutation_rate = max_mutation_rate
        self._reports: list[QualityReport] = []
    
    def check(self, result: dict) -> QualityReport:
        """执行完整质量检查."""
        report = QualityReport(timestamp=time.time())
        
        # 门禁1: 功能检查 - 输出是否有效
        func_check = self._check_functional(result)
        report.checks.append(func_check)
        
        # ��禁2: 性能检查 - 适应度提升
        perf_check = self._check_performance(result)
        report.checks.append(perf_check)
        
        # 门禁3: 可靠性检查 - 变异率
        reliability_check = self._check_reliability(result)
        report.checks.append(reliability_check)
        
        # 门禁4: 多样性检查 - 种群多样性
        diversity_check = self._check_diversity(result)
        report.checks.append(diversity_check)
        
        # 门禁5: 收敛性检查 - 是否过度拟合
        convergence_check = self._check_convergence(result)
        report.checks.append(convergence_check)
        
        # 综合决策
        fail_count = sum(1 for c in report.checks if c.result == GateResult.FAIL)
        warn_count = sum(1 for c in report.checks if c.result == GateResult.WARN)
        
        if fail_count > 0:
            report.overall = GateResult.FAIL
        elif warn_count >= 3:
            report.overall = GateResult.WARN
        else:
            report.overall = GateResult.PASS
        
        self._reports.append(report)
        return report
    
    def _check_functional(self, result: dict) -> GateCheck:
        """功能检查: 输出是否有效."""
        check = GateCheck(name="functional")
        
        # 检查是否有有效输出
        has_output = "result" in result or "individuals" in result or "best_fitness" in result
        if not has_output:
            check.result = GateResult.FAIL
            check.message = "无有效输出"
            return check
        
        # 检查适应度是否在有效范围
        fitness = result.get("best_fitness", result.get("fitness", 0))
        if isinstance(fitness, (int, float)):
            check.score = min(1.0, max(0.0, fitness))
            if fitness < self.fitness_threshold:
                check.result = GateResult.WARN
                check.message = f"适应度偏低: {fitness:.3f}"
            else:
                check.result = GateResult.PASS
                check.message = f"适应度正常: {fitness:.3f}"
        else:
            check.result = GateResult.FAIL
            check.message = "适应度非数值"
        
        return check
    
    def _check_performance(self, result: dict) -> GateCheck:
        """性能检查: 适应度提升."""
        check = GateCheck(name="performance")
        
        prev_fitness = result.get("prev_fitness", 0)
        curr_fitness = result.get("best_fitness", result.get("fitness", 0))
        
        if isinstance(prev_fitness, (int, float)) and isinstance(curr_fitness, (int, float)):
            improvement = curr_fitness - prev_fitness
            check.score = min(1.0, max(0.0, improvement + 0.5))  # 归一化
            
            if improvement < -0.1:
                check.result = GateResult.WARN
                check.message = f"适应度下降: {improvement:.3f}"
            elif improvement > 0.05:
                check.result = GateResult.PASS
                check.message = f"适应度提升: {improvement:.3f}"
            else:
                check.result = GateResult.PASS
                check.message = f"适应度稳定: {improvement:.3f}"

        else:
            # prev/curr fitness 非数值时给默认分, 不覆盖已算出的真实分
            check.score = 0.8  # 默认
        return check
    
    def _check_reliability(self, result: dict) -> GateCheck:
        """可靠性检查: 变异率."""
        check = GateCheck(name="reliability")
        
        mutation_rate = result.get("mutation_rate", 0.1)
        if isinstance(mutation_rate, (int, float)):
            # 可靠性评分必须落在 [0,1] 质量分区间 (与 functional/performance/diversity 门一致);
            # 当 mutation_rate 偏离 0.1 过大(如 >1.1 或 < -0.9, 来自未校验的 evolution result)
            # 原式 1.0 - abs(...) 会产出负数, 污染 QualityReport.avg_score 与 get_stats() 聚合。
            check.score = min(1.0, max(0.0, 1.0 - abs(mutation_rate - 0.1)))  # 理想值0.1, 限定[0,1]
            if mutation_rate > self.max_mutation_rate:
                check.result = GateResult.WARN
                check.message = f"变异率过高: {mutation_rate:.3f}"
            else:
                check.result = GateResult.PASS
                check.message = f"变异率正常: {mutation_rate:.3f}"
        
        return check
    
    def _check_diversity(self, result: dict) -> GateCheck:
        """多样性检查: 种群多样性."""
        check = GateCheck(name="diversity")
        
        diversity = result.get("diversity", 0.5)
        if isinstance(diversity, (int, float)):
            check.score = min(1.0, diversity * 2)  # 多样性越高越好
            if diversity < 0.1:
                check.result = GateResult.WARN
                check.message = f"多样性过低: {diversity:.3f}"
            else:
                check.result = GateResult.PASS
                check.message = f"多样性正常: {diversity:.3f}"
        
        return check
    
    def _check_convergence(self, result: dict) -> GateCheck:
        """收敛性检查: 是否过度拟合."""
        check = GateCheck(name="convergence")
        
        generations = result.get("generations", result.get("generation", 0))
        converged = result.get("converged", False)
        
        if isinstance(generations, int) and generations > 100:
            check.result = GateResult.WARN
            check.message = f"进化代数过多: {generations}"
            check.score = 0.5
        else:
            check.result = GateResult.PASS
            check.message = f"收敛正常 (代数: {generations})"
            check.score = 0.9
        
        return check
    
    def get_stats(self) -> dict:
        """获取质量统计."""
        if not self._reports:
            return {"checks": 0, "pass_rate": 1.0}
        
        total_pass = sum(1 for r in self._reports if r.overall == GateResult.PASS)
        total_warn = sum(1 for r in self._reports if r.overall == GateResult.WARN)
        total_fail = sum(1 for r in self._reports if r.overall == GateResult.FAIL)
        
        return {
            "checks": len(self._reports),
            "pass": total_pass,
            "warn": total_warn,
            "fail": total_fail,
            "pass_rate": total_pass / len(self._reports),
            "avg_score": sum(r.avg_score for r in self._reports) / len(self._reports),
        }
    
    def get_gate_status(self, report: QualityReport | None = None) -> dict:
        """Return pass/fail status per gate with scores.

        Args:
            report: Optional specific report to check. If None, checks the last report.

        Returns:
            dict with per-gate status, pass/fail counts, and overall result.
        """
        if report is None:
            if not self._reports:
                return {"overall": "no_reports", "gates": {}}
            report = self._reports[-1]

        gate_status: dict[str, dict] = {}
        pass_count = 0
        fail_count = 0
        warn_count = 0

        for check in report.checks:
            result_str = check.result.value if hasattr(check.result, "value") else str(check.result)
            gate_status[check.name] = {
                "result": result_str,
                "score": round(check.score, 4),
                "message": check.message,
            }
            if check.result == GateResult.PASS:
                pass_count += 1
            elif check.result == GateResult.FAIL:
                fail_count += 1
            else:
                warn_count += 1

        return {
            "overall": report.overall.value if hasattr(report.overall, "value") else str(report.overall),
            "gates": gate_status,
            "pass_count": pass_count,
            "warn_count": warn_count,
            "fail_count": fail_count,
            "total_gates": len(report.checks),
            "pass_rate": round(report.pass_rate, 4),
            "avg_score": round(report.avg_score, 4),
            "timestamp": report.timestamp,
        }

    # 兼容别名: life.py 调用 check_step() 做 step-budget 门禁
    def check_step(self, step: str = "", step_number: int = 0, max_steps: int = 0) -> tuple:
        """检查步骤是否允许继续 (step-budget 门禁).

        基于步骤预算 (max_steps) 做门禁: 当 step_number 达到/超过 max_steps 时阻断,
        防止进化循环步数失控。max_steps<=0 视为不限制 (向后兼容旧调用方)。
        life.py 在 evolve 流水线以此返回值作为真实阻断判断 (if not allowed: BLOCKED)。
        """
        if max_steps > 0 and step_number >= max_steps:
            reason = (
                f"step budget exhausted: step {step_number} >= max {max_steps} "
                f"(step='{step}')"
            )
            logger.warning("EvolutionQualityGates blocked step: %s", reason)
            return False, reason
        return True, "step allowed"

    def record_step(self, step_id: str, action: str, information_gain: float = 0.0, **kwargs) -> dict:
        """记录进化步骤（兼容 runner.py API）。

        Args:
            step_id: 步骤标识符
            action: 执行的动作描述
            information_gain: 信息增益分数
            **kwargs: 额外参数

        Returns:
            记录结果字典
        """
        report = QualityReport(timestamp=time.time())
        check = GateCheck(
            name=action,
            score=min(1.0, max(0.0, information_gain)),
            result=GateResult.PASS if information_gain > 0.05 else GateResult.WARN,
            message=f"Step {step_id}: {action}, gain={information_gain:.4f}"
        )
        report.checks.append(check)
        self._reports.append(report)
        
        return {
            "step_id": step_id,
            "action": action,
            "information_gain": information_gain,
            "result": check.result.value,
            "score": check.score,
        }
