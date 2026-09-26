from __future__ import annotations

import inspect
from typing import Any, Callable, get_type_hints

from pydantic import ConfigDict, TypeAdapter, create_model

from .schemas import RegisteredTool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    def register_service(self, service: object) -> None:
        for _, method in inspect.getmembers(service, predicate=inspect.ismethod):
            if not getattr(method, "__agent_tool__", False):
                continue
            name = getattr(method, "__agent_tool_name__", method.__name__)
            description = getattr(method, "__agent_tool_description__", "")
            schema = self._build_input_schema(method)
            if name in self._tools:
                raise ValueError(f"重复 tool name: {name}")
            self._tools[name] = RegisteredTool(name, description, method, schema)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"未知 tool: {name}")
        kwargs = self._validate_arguments(tool.callable, arguments)
        result = tool.callable(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    def names(self) -> list[str]:
        return sorted(self._tools)

    def _build_input_schema(self, func: Callable[..., Any]) -> dict[str, Any]:
        sig = inspect.signature(func)
        hints = get_type_hints(func)
        fields = {}
        for name, param in sig.parameters.items():
            annotation = hints.get(name, Any)
            default = ... if param.default is inspect._empty else param.default
            fields[name] = (annotation, default)
        model = create_model(
            f"{func.__name__}Input",
            __config__=ConfigDict(extra="forbid"),
            **fields,
        )
        return model.model_json_schema()

    def _validate_arguments(
        self,
        func: Callable[..., Any],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        sig = inspect.signature(func)
        unknown = sorted(set(arguments) - set(sig.parameters))
        if unknown:
            raise ValueError(f"未知参数: {', '.join(unknown)}")

        hints = get_type_hints(func)
        parsed: dict[str, Any] = {}
        for name, param in sig.parameters.items():
            if name not in arguments:
                if param.default is inspect._empty:
                    raise ValueError(f"缺少参数: {name}")
                continue
            annotation = hints.get(name, Any)
            parsed[name] = TypeAdapter(annotation).validate_python(arguments[name])
        return parsed
