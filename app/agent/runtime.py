from __future__ import annotations

import asyncio
import json
from typing import Any
from weakref import WeakValueDictionary

from app.agent.memory.manager import MemoryManager
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools.registry import ToolRegistry
from app.application.search.boss_search_options import BossSearchOptionsService
from app.application.search.job_seek_task_service import JobSeekTaskService
from app.infrastructure.database.repositories.chat_repository import ChatRepository
from app.infrastructure.llm import LLMClient

MAX_TOOL_ROUNDS = 6
HISTORY_LIMIT = 30


class AgentRuntime:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        memory: MemoryManager,
        chat_repository: ChatRepository,
        job_seek_task_service: JobSeekTaskService,
        boss_search_options: BossSearchOptionsService,
    ):
        self.llm: LLMClient = llm
        self.registry: ToolRegistry = registry
        self.memory: MemoryManager = memory
        self.chat_repository: ChatRepository = chat_repository
        self.job_seek_task_service: JobSeekTaskService = job_seek_task_service
        self.boss_search_options: BossSearchOptionsService = boss_search_options
        self._conversation_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    def list_messages(self, conversation_id: str, limit: int = 100) -> list[dict[str, str]]:
        """返回指定会话最近的聊天记录，按时间正序排列。"""
        return self.chat_repository.recent(conversation_id, limit)

    def list_conversations(self, limit: int = 50) -> list[dict[str, object]]:
        """返回已有会话列表，最近有消息的会话排在前面。"""
        return self.chat_repository.list_conversations(limit)

    async def run(self, conversation_id: str, user_message: str) -> str:
        """同一会话串行执行；不同会话之间仍可并发。"""
        lock = self._conversation_locks.setdefault(conversation_id, asyncio.Lock())
        async with lock:
            return await self._run_locked(conversation_id, user_message)

    async def _run_locked(self, conversation_id: str, user_message: str) -> str:
        content = user_message.strip()
        if not content:
            raise ValueError("消息不能为空")
        self.chat_repository.add(conversation_id, "user", content)

        memory = self.memory.build(conversation_id, HISTORY_LIMIT)
        job_seek_tasks = self.job_seek_task_service.list_active_tasks(limit=50)
        context_text = json.dumps(
            {
                "search_parameter_guide": self.boss_search_options.semantic_guide(),
                "profile": memory["profile"].model_dump(),
                "job_seek_tasks": [
                    task.model_dump(mode="json") for task in job_seek_tasks
                ],
            },
            ensure_ascii=False,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n当前上下文：\n" + context_text},
            *memory["history"][:-1],
            {"role": "user", "content": content},
        ]

        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.llm.chat(messages=messages, tools=self.registry.schemas())
            if not response.tool_calls:
                reply = response.content or "（模型没有生成可回复内容。）"
                self.chat_repository.add(conversation_id, "assistant", reply)
                return reply

            assistant_calls: list[dict[str, Any]] = []
            for call in response.tool_calls:
                assistant_calls.append({
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
                })
            messages.append({"role": "assistant", "content": response.content or None, "tool_calls": assistant_calls})

            for call in response.tool_calls:
                try:
                    result = await self.registry.execute(call.name, call.arguments)
                    if hasattr(result, "model_dump"):
                        payload = result.model_dump(mode="json")
                    elif isinstance(result, list):
                        payload = [x.model_dump(mode="json") if hasattr(x, "model_dump") else x for x in result]
                    else:
                        payload = result
                    tool_content = json.dumps(payload, ensure_ascii=False, default=str)
                except Exception as exc:  # tool error is returned to model; runtime stays alive
                    tool_content = json.dumps({"error": str(exc)}, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": tool_content})

        reply = "工具调用轮次超过上限，请缩小本次操作范围后重试。"
        self.chat_repository.add(conversation_id, "assistant", reply)
        return reply
