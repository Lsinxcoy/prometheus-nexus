"""SubAgentContract — 子代理契约管理与SLA监控.

基于:
- "Service Level Agreements for Multi-Agent Systems"
  - 契约定义: 输入/输出规范+时效承诺
  - SLA监控: 响应时间+成功率追踪
  - 违约检测: 超时/格式不符/质量不达标
  - 信用评分: 历史履约记录

算法:
    create_contract(spec):
        1. 验证契约规范完整性
        2. 生成契约ID和元数据
        3. 记录创建时间
    
    verify_fulfillment(result):
        1. 检查响应时间是否在SLA内
        2. 验���输出格式是否符合契约
        3. 计算质量得分
        4. 更新信用评分

复杂度:
    verify_fulfillment(): O(1)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

import time
import hashlib


class SubAgentContract:
    """子代理契约管理 — SLA驱动的任务委派.
    
    契约化子代理交互，确保服务质量可度量、可追溯.
    """
    
    def __init__(self):
        """初始化契约管理器."""
        self._contracts: dict[str, dict] = {}
        self._fulfillments: list[dict] = []
        self._agent_credits: dict[str, float] = {}
    
    def create_contract(self, agent_id: str, task: str,
                        response_time_s: float = 30.0,
                        output_schema: dict | None = None,
                        quality_threshold: float = 0.7) -> dict:
        """创建子代理契约.
        
        Args:
            agent_id: 子代理ID
            task: 任务描述
            response_time_s: SLA响应时间(秒)
            output_schema: 输出格式规范
            quality_threshold: 最低质量要求
        
        Returns:
            dict: 契约信息
        """
        contract_id = hashlib.md5(
            f"{agent_id}:{task}:{time.time()}".encode()
        ).hexdigest()[:12]
        
        contract = {
            "id": contract_id,
            "agent_id": agent_id,
            "task": task,
            "response_time_s": response_time_s,
            "output_schema": output_schema or {},
            "quality_threshold": quality_threshold,
            "created_at": time.time(),
            "status": "active",
        }
        
        self._contracts[contract_id] = contract
        return contract
    
    def verify_fulfillment(self, contract_id: str, result: dict) -> dict:
        """验证契约履行情况.
        
        Args:
            contract_id: 契约ID
            result: 子代理返回结果
        
        Returns:
            dict: 验证报告
        """
        contract = self._contracts.get(contract_id)
        if not contract:
            return {"valid": False, "reason": "contract not found"}
        
        agent_id = contract["agent_id"]
        created_at = contract["created_at"]
        fulfilled_at = time.time()
        
        # 1. 响应时间检查
        response_time = fulfilled_at - created_at
        sla_met = response_time <= contract["response_time_s"]
        sla_breach_pct = max(0, (response_time - contract["response_time_s"]) / contract["response_time_s"])
        
        # 2. 输出格式检查
        schema = contract.get("output_schema", {})
        schema_valid = True
        schema_errors = []
        
        for field, field_type in schema.items():
            if field not in result:
                schema_valid = False
                schema_errors.append(f"missing field: {field}")
            elif field_type == "str" and not isinstance(result[field], str):
                schema_valid = False
                schema_errors.append(f"wrong type for {field}: expected str")
            elif field_type == "list" and not isinstance(result[field], list):
                schema_valid = False
                schema_errors.append(f"wrong type for {field}: expected list")
        
        # 3. 质量评分
        quality = self._estimate_quality(result, contract)
        quality_met = quality >= contract["quality_threshold"]
        
        # 4. 综合判断
        valid = sla_met and schema_valid and quality_met
        
        # 5. 更新信用评分
        current_credit = self._agent_credits.get(agent_id, 1.0)
        if valid:
            new_credit = min(1.0, current_credit * 0.99 + 0.01)
        else:
            new_credit = max(0.0, current_credit * 0.95 - 0.05)
        self._agent_credits[agent_id] = new_credit
        
        report = {
            "contract_id": contract_id,
            "agent_id": agent_id,
            "valid": valid,
            "sla_met": sla_met,
            "response_time_s": round(response_time, 2),
            "sla_limit_s": contract["response_time_s"],
            "sla_breach_pct": round(sla_breach_pct, 4),
            "schema_valid": schema_valid,
            "schema_errors": schema_errors,
            "quality_score": round(quality, 4),
            "quality_met": quality_met,
            "agent_credit": round(new_credit, 4),
        }
        
        self._fulfillments.append(report)
        if len(self._fulfillments) > 500:
            self._fulfillments = self._fulfillments[-250:]
        
        contract["status"] = "fulfilled" if valid else "breached"
        
        return report
    
    def _estimate_quality(self, result: dict, contract: dict) -> float:
        """估算结果质量得分.
        
        Args:
            result: 子代理结果
            contract: 契约
        
        Returns:
            float: 质量得分 [0, 1]
        """
        score = 0.0
        factors = 0
        
        # 内容长度因子
        content = result.get("content", "")
        if isinstance(content, str):
            length_score = min(1.0, len(content) / 500)
            score += length_score
            factors += 1
        
        # 结构完整性因子
        if contract.get("output_schema"):
            filled_fields = sum(
                1 for f in contract["output_schema"] if f in result
            )
            total_fields = len(contract["output_schema"])
            schema_score = filled_fields / max(total_fields, 1)
            score += schema_score
            factors += 1
        
        # 默认分
        if factors == 0:
            return 0.5
        
        return score / factors
    
    def get_agent_credit(self, agent_id: str) -> float:
        """获取子代理信用评分.
        
        Args:
            agent_id: 子代理ID
        
        Returns:
            float: 信用评分 [0, 1]
        """
        return self._agent_credits.get(agent_id, 1.0)
    
    def get_stats(self) -> dict:
        """获取统计."""
        total = len(self._fulfillments)
        valid_count = sum(1 for f in self._fulfillments if f.get("valid"))
        
        return {
            "total_contracts": len(self._contracts),
            "total_fulfillments": total,
            "fulfillment_rate": round(valid_count / max(total, 1), 4),
            "agents_tracked": len(self._agent_credits),
        }
