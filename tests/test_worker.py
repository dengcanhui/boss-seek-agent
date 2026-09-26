import asyncio
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.search.boss_search_config_compiler import BossSearchConfigCompiler
from app.application.search.job_seek_task_service import JobSeekTaskService
from app.domain.search.enums import JobSeekTaskStatus
from app.domain.search.models import JobSeekTaskParams
from app.execution.worker import JobSeekWorker
from app.infrastructure.database.database import Base
from app.infrastructure.database.repositories.job_seek_task_repository import (
    JobSeekTaskRepository,
)


class SuccessExecutor:
    def __init__(self):
        self.executed_ids: list[int] = []

    async def execute(self, job_seek_task) -> None:
        self.executed_ids.append(job_seek_task.id)


class CancelledExecutor:
    async def execute(self, job_seek_task) -> None:
        raise asyncio.CancelledError


class BlockingExecutor:
    def __init__(self):
        self.started = asyncio.Event()
        self.started_task_id: int | None = None
        self.cancelled = False

    async def execute(self, job_seek_task) -> None:
        self.started_task_id = job_seek_task.id
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def make_repository(tmp_path: Path) -> JobSeekTaskRepository:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'worker.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)
    return JobSeekTaskRepository(session)


def make_service(repository: JobSeekTaskRepository) -> JobSeekTaskService:
    return JobSeekTaskService(repository, BossSearchConfigCompiler())


def create_task(repository: JobSeekTaskRepository, *, query="Python", priority=0):
    return make_service(repository).create_task(
        JobSeekTaskParams(query=query, city="杭州", priority=priority)
    )


def test_worker_run_once_completes_claimed_task(tmp_path: Path):
    repository = make_repository(tmp_path)
    task = create_task(repository)
    executor = SuccessExecutor()
    worker = JobSeekWorker(repository, executor, poll_interval=0.01)
    worker.prepare_start()

    assert asyncio.run(worker.run_once()) is True
    assert executor.executed_ids == [task.id]
    assert repository.get(task.id).status == JobSeekTaskStatus.COMPLETED


def test_executor_cancelled_without_user_control_marks_task_stopped(tmp_path: Path):
    repository = make_repository(tmp_path)
    task = create_task(repository)
    worker = JobSeekWorker(repository, CancelledExecutor(), poll_interval=0.01)
    worker.prepare_start()

    assert asyncio.run(worker.run_once()) is True
    assert repository.get(task.id).status == JobSeekTaskStatus.STOPPED


def test_stopping_worker_marks_running_task_stopped_and_cancels_execution(tmp_path: Path):
    repository = make_repository(tmp_path)
    task = create_task(repository)
    executor = BlockingExecutor()
    worker = JobSeekWorker(
        repository,
        executor,
        poll_interval=0.01,
        control_poll_interval=0.01,
    )

    async def scenario():
        worker.prepare_start()
        loop_task = asyncio.create_task(worker.run_forever())
        await asyncio.wait_for(executor.started.wait(), timeout=1)
        assert repository.get(task.id).status == JobSeekTaskStatus.RUNNING

        worker.request_stop()
        await asyncio.wait_for(loop_task, timeout=1)

    asyncio.run(scenario())

    assert executor.cancelled is True
    assert repository.get(task.id).status == JobSeekTaskStatus.STOPPED
    assert worker.running is False
    assert worker.active_job_seek_task_id is None


def test_next_start_does_not_resume_stopped_task(tmp_path: Path):
    repository = make_repository(tmp_path)
    stopped_task = create_task(repository, query="Python", priority=1)
    pending_task = create_task(repository, query="Agent", priority=2)
    repository.set_status(stopped_task.id, JobSeekTaskStatus.STOPPED)

    claimed = repository.claim_next()

    assert claimed is not None
    assert claimed.id == pending_task.id
    assert repository.get(stopped_task.id).status == JobSeekTaskStatus.STOPPED


def test_user_cancel_running_task_interrupts_executor_without_stopping_worker(tmp_path: Path):
    repository = make_repository(tmp_path)
    service = make_service(repository)
    task = service.create_task(JobSeekTaskParams(query="Python", city="杭州"))
    executor = BlockingExecutor()
    worker = JobSeekWorker(
        repository,
        executor,
        poll_interval=0.01,
        control_poll_interval=0.01,
    )
    worker.prepare_start()

    async def scenario():
        run_once_task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(executor.started.wait(), timeout=1)

        cancelled = service.cancel_task(task.id)
        assert cancelled.status == JobSeekTaskStatus.CANCELLED

        assert await asyncio.wait_for(run_once_task, timeout=1) is True

    asyncio.run(scenario())
    assert executor.cancelled is True
    assert repository.get(task.id).status == JobSeekTaskStatus.CANCELLED


def test_repository_recovers_stale_running_tasks_as_stopped(tmp_path: Path):
    repository = make_repository(tmp_path)
    task = create_task(repository)
    claimed = repository.claim_next()
    assert claimed is not None
    assert claimed.status == JobSeekTaskStatus.RUNNING

    assert repository.recover_running_as_stopped() == 1
    assert repository.get(task.id).status == JobSeekTaskStatus.STOPPED
    assert repository.recover_running_as_stopped() == 0
