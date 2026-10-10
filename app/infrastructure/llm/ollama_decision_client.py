from __future__ import annotations

from typing import Any

import httpx


class OllamaDecisionClient:
    """Ollama System One 的 HTTP 适配器，不包含岗位业务规则。"""

    def __init__(
        self,
        *,
        model: str = "tev1:4b",
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.model: str = model
        self.client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        )

    async def evaluate(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
    ) -> dict[str, Any]:
        """执行远程决策请求，并返回原始 System One 结果。"""
        response = await self.client.post(
            "/v1/systemone",
            json={
                "model": self.model,
                "state": state,
                "questions": questions,
            },
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Ollama System One 返回的数据不是 JSON 对象")
        return result

    async def aclose(self) -> None:
        await self.client.aclose()
