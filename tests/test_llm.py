import asyncio
from types import SimpleNamespace

import app.infrastructure.llm.openai_client as llm_module
from app.infrastructure.llm.openai_client import LLMClient


class FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.request = None

    async def create(self, **kwargs):
        self.request = kwargs
        return self.response


class FakeClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=FakeCompletions(response))
        self.closed = False

    async def close(self):
        self.closed = True


def make_response(*, content="ok", arguments='{"keyword":"Python"}'):
    tool_call = SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(
            name="search_jobs",
            arguments=arguments,
        ),
    )
    message = SimpleNamespace(content=content, tool_calls=[tool_call])
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def test_llm_client_uses_openai_compatible_configuration(monkeypatch):
    fake_client = FakeClient(make_response())
    client_config = {}

    def fake_async_openai(**kwargs):
        client_config.update(kwargs)
        return fake_client

    monkeypatch.setattr(llm_module, "AsyncOpenAI", fake_async_openai)

    client = LLMClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
    )

    response = asyncio.run(
        client.chat(
            messages=[{"role": "user", "content": "找 Python 工作"}],
            tools=[{"type": "function", "function": {"name": "search_jobs"}}],
        )
    )

    assert client_config == {
        "api_key": "test-key",
        "base_url": "https://api.deepseek.com",
        "timeout": 60.0,
        "max_retries": 2,
    }
    assert fake_client.chat.completions.request["model"] == "deepseek-flash"
    assert fake_client.chat.completions.request["reasoning_effort"] == "high"
    assert fake_client.chat.completions.request["extra_body"] == {
        "thinking": {"type": "enabled"}
    }
    assert fake_client.chat.completions.request["stream"] is False
    assert response.content == "ok"
    assert response.tool_calls[0].name == "search_jobs"
    assert response.tool_calls[0].arguments == {"keyword": "Python"}


def test_llm_client_uses_default_reasoning_options(monkeypatch):
    response = make_response()
    response.choices[0].message.tool_calls = []
    fake_client = FakeClient(response)

    monkeypatch.setattr(llm_module, "AsyncOpenAI", lambda **_: fake_client)

    client = LLMClient(
        api_key="key",
        model="model",
    )
    asyncio.run(
        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        )
    )

    request = fake_client.chat.completions.request
    assert "tools" not in request
    assert request["reasoning_effort"] == "high"
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}


def test_llm_client_closes_sdk_client(monkeypatch):
    fake_client = FakeClient(make_response())
    monkeypatch.setattr(llm_module, "AsyncOpenAI", lambda **_: fake_client)

    client = LLMClient(api_key="key", model="model")
    asyncio.run(client.aclose())

    assert fake_client.closed is True
