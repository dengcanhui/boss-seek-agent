import asyncio

import pytest
from pydantic import BaseModel

from app.agent.tools.decorator import agent_tool
from app.agent.tools.registry import ToolRegistry
from app.application.search.job_seek_task_service import JobSeekTaskService


class Input(BaseModel):
    value: int


class Service:
    @agent_tool(description="demo")
    def demo(self, data: Input):
        return data.value * 2


def test_registry_reflection():
    registry = ToolRegistry()
    registry.register_service(Service())
    assert "demo" in registry.names()
    assert asyncio.run(registry.execute("demo", {"data": {"value": 3}})) == 6


def test_job_seek_task_tools_do_not_expose_worker_lifecycle_controls():
    registry = ToolRegistry()
    registry.register_service(JobSeekTaskService(object(), object()))

    names = registry.names()
    assert "start_task" not in names
    assert "stop_task" not in names
    assert "create_task" in names
    assert "cancel_task" in names


def test_registry_schema_and_runtime_reject_unknown_arguments():
    registry = ToolRegistry()
    registry.register_service(Service())
    schema = registry.schemas()[0]["function"]["parameters"]

    assert schema["additionalProperties"] is False
    with pytest.raises(ValueError, match="未知参数: unexpected"):
        asyncio.run(
            registry.execute(
                "demo",
                {"data": {"value": 3}, "unexpected": True},
            )
        )
