from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolCall:
    """大模型返回的一次工具调用请求。"""

    # 本次工具调用的唯一 ID，后续 tool 消息需要原样带回。
    id: str
    # 要执行的工具名称。
    name: str
    # 已解析成字典的工具调用参数。
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMResponse:
    """LLMClient 对上层暴露的统一响应结构。"""

    # 模型直接生成的文本内容；纯工具调用时可能为空字符串。
    content: str = ""
    # 模型在本轮请求中要求执行的工具列表。
    tool_calls: list[ToolCall] = field(default_factory=list)
