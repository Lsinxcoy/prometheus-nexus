"""XMemoryAdapter — X系统内存格式适配器.

基于:
- Omega系统: X/Y/Z三系统内存格式
  - 格式检测: 自动识别数据格式
  - 模式映射: 字段名转换
  - 数据转换: 类型和结构转换
  - 反向适配: 从Omega格式转回X格式

算法:
    adapt(data):
        1. 检测输入格式
        2. 应用模式映射
        3. 转换数据类型
        4. 添加元数据
        5. 返回适配结果

复杂度:
    adapt(): O(F) 其中F=字段数
"""
from __future__ import annotations



import logging
import time
logger = logging.getLogger(__name__)


class XMemoryAdapter:
    """X系统内存适配器.
    
    支持X系统到Omega格式的转换.
    """
    
    def __init__(self):
        """初始化."""
        self._adaptations: list[dict] = []
        self._error_count = 0
        
        # X→Omega 字段映射
        self._x_to_omega: dict[str, str] = {
            "id": "node_id",
            "content": "text",
            "importance": "utility",
            "tags": "labels",
            "created": "timestamp",
            "last_accessed": "last_used",
            "access_count": "frequency",
            "category": "category",
            "source": "origin",
            "confidence": "confidence",
            "context": "context_window",
            "relations": "edges",
        }
        
        # 反向映射 (Omega→X)
        self._omega_to_x = {v: k for k, v in self._x_to_omega.items()}
        
        # 类型转换映射
        self._type_converters = {
            "timestamp": self._to_timestamp,
            "utility": self._to_float,
            "frequency": self._to_int,
        }
    
    def detect_format(self, data: dict) -> str:
        """检测数据格式.
        
        Args:
            data: 输入数据
        
        Returns:
            str: 格式类型('x', 'omega', 'unknown')
        """
        if not data:
            return "unknown"
        
        # X系统特征字段
        x_indicators = {"id", "content", "importance", "tags"}
        # Omega特征字段
        omega_indicators = {"node_id", "text", "utility", "labels"}
        
        keys = set(data.keys())
        x_score = len(keys & x_indicators)
        omega_score = len(keys & omega_indicators)
        
        if x_score > omega_score and x_score >= 2:
            return "x"
        if omega_score > x_score and omega_score >= 2:
            return "omega"
        
        return "unknown"
    
    def adapt(self, data: dict | None = None) -> dict:
        """将X格式适配为Omega格式.
        
        Args:
            data: X系统数据
        
        Returns:
            dict: 适配结果
        """
        data = data or {}
        
        try:
            adapted = {}
            mapped_count = 0
            
            for key, value in data.items():
                mapped_key = self._x_to_omega.get(key, key)
                
                # 类型转换
                if mapped_key in self._type_converters:
                    try:
                        value = self._type_converters[mapped_key](value)
                    except (ValueError, TypeError) as e:
                        logger.warning("Type conversion failed for %s: %s", mapped_key, e)
                
                adapted[mapped_key] = value
                if mapped_key != key:
                    mapped_count += 1
            
            # 添加适配器元数据
            adapted["_adapter"] = "XMemoryAdapter"
            adapted["_schema_version"] = "1.0"
            adapted["_adapted_at"] = time.time()
            
            result = {
                "adapted": True,
                "source": "X",
                "target": "omega",
                "mapped_fields": mapped_count,
                "total_fields": len(data),
                "data": adapted,
            }
            
            self._adaptations.append({
                "action": "x_to_omega",
                "timestamp": time.time(),
                "fields": len(data),
            })
            
            return result
        
        except Exception as e:
            self._error_count += 1
            return {
                "adapted": False,
                "error": str(e),
                "source": "X",
            }
    
    def reverse_adapt(self, data: dict) -> dict:
        """将Omega格式转回X格式.
        
        Args:
            data: Omega格式数据
        
        Returns:
            dict: X格式数据
        """
        adapted = {}
        
        for key, value in data.items():
            if key.startswith('_'):
                continue  # 跳过元数据
            mapped_key = self._omega_to_x.get(key, key)
            adapted[mapped_key] = value
        
        self._adaptations.append({
            "action": "omega_to_x",
            "timestamp": time.time(),
            "fields": len(adapted),
        })
        
        return adapted
    
    def batch_adapt(self, items: list[dict]) -> list[dict]:
        """批量适配.
        
        Args:
            items: X系统数据列表
        
        Returns:
            list: 适配结果列表
        """
        results = []
        for item in items:
            result = self.adapt(item)
            results.append(result.get("data", result))
        return results
    
    @staticmethod
    def _to_timestamp(value) -> float:
        """转为时间戳."""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                logger.warning(
                    "XMemoryAdapter._to_timestamp: 非法时间戳 %r, 回退 0.0(epoch)", value
                )
                return 0.0
        logger.warning(
            "XMemoryAdapter._to_timestamp: 非数值类型 %r, 回退 0.0(epoch)", value
        )
        return 0.0

    @staticmethod
    def _to_float(value) -> float:
        """转为浮点数."""
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(
                "XMemoryAdapter._to_float: 非法浮点 %r, 回退 0.0", value
            )
            return 0.0

    @staticmethod
    def _to_int(value) -> int:
        """转为整数."""
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning(
                "XMemoryAdapter._to_int: 非法整数 %r, 回退 0", value
            )
            return 0
    
    def get_stats(self) -> dict:
        """获取统计."""
        actions = {"x_to_omega": 0, "omega_to_x": 0}
        for a in self._adaptations:
            action = a.get("action", "unknown")
            actions[action] = actions.get(action, 0) + 1
        
        return {
            "total_adaptations": len(self._adaptations),
            "actions": actions,
            "errors": self._error_count,
        }
