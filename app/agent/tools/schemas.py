from dataclasses import dataclass
from typing import Any, Callable


@dataclass(slots=True)
class RegisteredTool:
    """注册到 Agent 的工具元数据。"""

    # 暴露给大模型的工具名称。
    name: str
    # 暴露给大模型的工具用途说明。
    description: str
    # 实际执行该工具的 Python 可调用对象。
    callable: Callable[..., Any]
    # OpenAI tool calling 使用的 JSON Schema 参数定义。
    input_schema: dict[str, Any]
