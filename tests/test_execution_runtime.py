import asyncio
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.execution.job_seek_execution_service import JobSeekExecutionService
from app.application.search.boss_search_config_compiler import BossSearchConfigCompiler
from app.application.search.job_seek_task_service import JobSeekTaskService
from app.domain.search.enums import JobSeekTaskStatus
from app.domain.search.models import JobSeekTaskParams
from app.execution.worker import JobSeekWorker
from app.infrastructure.database.database import Base
from app.infrastructure.database.repositories.job_seek_task_repository import (
    JobSeekTaskRepository,
)


class BlockingExecutor:
    def __init__(self):
        self.started = asyncio.Event()
        self.started_task_id: int | None = None
        self.cancelled = False

    def reset(self) -> None:
        self.started = asyncio.Event()
        self.started_task_id = None
        self.cancelled = False

    async def execute(self, job_seek_task) -> None:
        self.started_task_id = job_seek_task.id
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def make_runtime(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'runtime.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)
    repository = JobSeekTaskRepository(session)
    service = JobSeekTaskService(repository, BossSearchConfigCompiler())
    executor = BlockingExecutor()
    worker = JobSeekWorker(
        repository,
        executor,
        poll_interval=0.01,
        control_poll_interval=0.01,
    )
    return JobSeekExecutionService(worker), repository, service, executor


def test_execution_service_stop_stops_executor_and_next_start_uses_pending(tmp_path: Path):
    runtime, repository, service, executor = make_runtime(tmp_path)
    first = service.create_task(
        JobSeekTaskParams(query="Python", city="杭州", priority=1)
    )
    second = service.create_task(
        JobSeekTaskParams(query="Agent", city="杭州", priority=2)
    )

    async def scenario():
        started = await runtime.start()
        assert started.active is True
        await asyncio.wait_for(executor.started.wait(), timeout=1)
        assert executor.started_task_id == first.id
        assert repository.get(first.id).status == JobSeekTaskStatus.RUNNING

        stopped = await runtime.stop()
        assert stopped.active is False
        assert stopped.current_job_seek_task_id is None
        assert executor.cancelled is True
        assert repository.get(first.id).status == JobSeekTaskStatus.STOPPED
        assert repository.get(second.id).status == JobSeekTaskStatus.PENDING

        executor.reset()
        restarted = await runtime.start()
        assert restarted.active is True
        await asyncio.wait_for(executor.started.wait(), timeout=1)
        assert executor.started_task_id == second.id
        assert repository.get(first.id).status == JobSeekTaskStatus.STOPPED
        assert repository.get(second.id).status == JobSeekTaskStatus.RUNNING

        await runtime.stop()

    asyncio.run(scenario())


def test_execution_service_start_and_stop_are_idempotent(tmp_path: Path):
    runtime, _, _, _ = make_runtime(tmp_path)

    async def scenario():
        first = await runtime.start()
        second = await runtime.start()
        assert first.active is True
        assert second.active is True

        stopped = await runtime.stop()
        stopped_again = await runtime.stop()
        assert stopped.active is False
        assert stopped_again.active is False

    asyncio.run(scenario())
