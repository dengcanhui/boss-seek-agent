from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.infrastructure.llm.base import LLMResponse, ToolCall


class LLMClient:
    """通用 OpenAI-compatible LLM 客户端。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=60.0,
            max_retries=2,
        )

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            request["tools"] = tools
        request["reasoning_effort"] = "high"
        request["extra_body"] = {"thinking": {"type": "enabled"}}

        response = await self.client.chat.completions.create(**request)
        message = response.choices[0].message

        tool_calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            if call.type != "function":
                continue
            tool_calls.append(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=json.loads(call.function.arguments or "{}"),
                )
            )

        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
        )

    async def aclose(self) -> None:
        await self.client.close()
