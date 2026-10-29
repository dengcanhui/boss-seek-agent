from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import httpx

logger = logging.getLogger("uvicorn.error.llm")


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
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        logger.info("[ollama] 请求 id=%s model=%s state=%s questions=%s", request_id, self.model,
                    json.dumps(state, ensure_ascii=False, default=str), json.dumps(questions, ensure_ascii=False, default=str))
        try:
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
            logger.info("[ollama] 返回 id=%s 耗时=%.3fs result=%s", request_id,
                        time.perf_counter() - started, json.dumps(result, ensure_ascii=False, default=str))
        except Exception:
            logger.exception("[ollama] 请求失败 id=%s 耗时=%.3fs", request_id, time.perf_counter() - started)
            raise
        return result

    async def aclose(self) -> None:
        await self.client.aclose()
