import asyncio

from app.agent.runtime import AgentRuntime
from app.infrastructure.llm.base import LLMResponse


class CaptureLLM:
    def __init__(self):
        self.messages = None

    async def chat(self, *, messages, tools):
        self.messages = messages
        return LLMResponse(content="ok")


class BlockingLLM:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def chat(self, *, messages, tools):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        await self.release.wait()
        self.active -= 1
        user_message = next(
            message["content"]
            for message in reversed(messages)
            if message["role"] == "user"
        )
        return LLMResponse(content=f"reply:{user_message}")


class FakeRegistry:
    def schemas(self):
        return []


class FakeProfile:
    def model_dump(self):
        return {}


class FakeMemory:
    def __init__(self, chat_repository):
        self.chat_repository = chat_repository

    def build(self, conversation_id, history_limit):
        return {
            "history": self.chat_repository.recent(conversation_id, history_limit),
            "profile": FakeProfile(),
        }


class FakeChatRepository:
    def __init__(self):
        self.rows = []

    def add(self, conversation_id, role, content):
        self.rows.append((conversation_id, role, content))

    def recent(self, conversation_id, limit):
        rows = [row for row in self.rows if row[0] == conversation_id][-limit:]
        return [{"role": role, "content": content} for _, role, content in rows]


class FakeJobSeekTasks:
    def list_active_tasks(self, limit=50):
        return []


class FakeBossSearchOptions:
    def semantic_guide(self):
        return {
            "allowed_values": {"salary": ["10-20K"]},
            "field_rules": {"city": "具体城市名称"},
        }


async def _same_conversation_is_serialized():
    chat = FakeChatRepository()
    llm = BlockingLLM()
    runtime = AgentRuntime(
        llm,
        FakeRegistry(),
        FakeMemory(chat),
        chat,
        FakeJobSeekTasks(),
        FakeBossSearchOptions(),
    )

    first = asyncio.create_task(runtime.run("same", "first"))
    await llm.started.wait()
    second = asyncio.create_task(runtime.run("same", "second"))
    await asyncio.sleep(0)

    assert llm.active == 1
    llm.release.set()
    assert await first == "reply:first"
    assert await second == "reply:second"
    assert llm.max_active == 1


async def _different_conversations_can_overlap():
    chat = FakeChatRepository()
    llm = BlockingLLM()
    runtime = AgentRuntime(
        llm,
        FakeRegistry(),
        FakeMemory(chat),
        chat,
        FakeJobSeekTasks(),
        FakeBossSearchOptions(),
    )

    first = asyncio.create_task(runtime.run("a", "first"))
    second = asyncio.create_task(runtime.run("b", "second"))

    for _ in range(10):
        if llm.active == 2:
            break
        await asyncio.sleep(0)

    assert llm.active == 2
    llm.release.set()
    await asyncio.gather(first, second)
    assert llm.max_active == 2


def test_agent_context_includes_search_parameter_guide():
    chat = FakeChatRepository()
    llm = CaptureLLM()
    runtime = AgentRuntime(
        llm,
        FakeRegistry(),
        FakeMemory(chat),
        chat,
        FakeJobSeekTasks(),
        FakeBossSearchOptions(),
    )

    assert asyncio.run(runtime.run("guide", "找工作")) == "ok"
    system_content = llm.messages[0]["content"]
    assert '"search_parameter_guide"' in system_content
    assert '"10-20K"' in system_content
    assert "具体城市名称" in system_content


def test_same_conversation_is_serialized():
    asyncio.run(_same_conversation_is_serialized())


def test_different_conversations_can_overlap():
    asyncio.run(_different_conversations_can_overlap())
