from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.search.boss_search_config_compiler import BossSearchConfigCompiler
from app.application.search.job_seek_task_service import JobSeekTaskService
from app.domain.search.enums import JobSeekTaskStatus
from app.domain.search.models import JobSeekTaskParams
from app.infrastructure.database import tables  # noqa: F401
from app.infrastructure.database.database import Base
from app.infrastructure.database.repositories.job_seek_task_repository import (
    JobSeekTaskRepository,
)


def make_service(tmp_path: Path) -> tuple[JobSeekTaskService, JobSeekTaskRepository]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)
    repository = JobSeekTaskRepository(session)
    return JobSeekTaskService(repository, BossSearchConfigCompiler()), repository


def test_create_task(tmp_path: Path):
    service, _ = make_service(tmp_path)
    task = service.create_task(JobSeekTaskParams(query="Python", city="杭州", priority=80))
    assert task.priority == 80
    assert task.config.query == "Python"
    assert task.config.city == "101210100"
    assert task.created_at.utcoffset() == timedelta(hours=8)
    assert task.updated_at.utcoffset() == timedelta(hours=8)
    assert task.config.jobType is None
    assert task.config.salary is None


def test_update_pending_task_keeps_existing_compiled_fields(tmp_path: Path):
    service, _ = make_service(tmp_path)
    task = service.create_task(
        JobSeekTaskParams(query="Python", city="杭州", degree=["本科"], priority=80)
    )

    updated = service.update_task(task.id, JobSeekTaskParams(salary="20-50K"))

    assert updated.config.city == "101210100"
    assert updated.config.degree == ["203"]
    assert updated.config.salary == "406"
    assert updated.priority == 80


def test_update_and_priority_only_allow_pending(tmp_path: Path):
    service, repository = make_service(tmp_path)
    task = service.create_task(JobSeekTaskParams(query="Python", city="杭州"))
    claimed = repository.claim_next()
    assert claimed is not None

    with pytest.raises(ValueError, match="只有 pending"):
        service.update_task(task.id, JobSeekTaskParams(salary="20-50K"))
    with pytest.raises(ValueError, match="只有 pending"):
        service.set_priority(task.id, 1)


def test_cancel_running_task(tmp_path: Path):
    service, repository = make_service(tmp_path)
    task = service.create_task(JobSeekTaskParams(query="Python", city="杭州"))
    claimed = repository.claim_next()
    assert claimed is not None
    assert claimed.status == JobSeekTaskStatus.RUNNING

    cancelled = service.cancel_task(task.id)
    assert cancelled.status == JobSeekTaskStatus.CANCELLED


def test_requeue_accepts_stopped_task_and_keeps_original(tmp_path: Path):
    service, repository = make_service(tmp_path)
    task = service.create_task(JobSeekTaskParams(query="Python", city="杭州", priority=20))
    repository.set_status(task.id, JobSeekTaskStatus.STOPPED)

    requeued = service.requeue_task(task.id, priority=5)

    assert requeued.id != task.id
    assert requeued.status == JobSeekTaskStatus.PENDING
    assert requeued.priority == 5
    assert repository.get(task.id).status == JobSeekTaskStatus.STOPPED


def test_requeue_rejects_pending_and_running(tmp_path: Path):
    service, repository = make_service(tmp_path)
    pending = service.create_task(JobSeekTaskParams(query="Python", city="杭州"))

    with pytest.raises(ValueError, match="允许重新入队"):
        service.requeue_task(pending.id)

    running = repository.claim_next()
    assert running is not None
    with pytest.raises(ValueError, match="允许重新入队"):
        service.requeue_task(running.id)


def test_delete_only_allows_pending_and_keeps_history_immutable(tmp_path: Path):
    service, repository = make_service(tmp_path)
    pending = service.create_task(JobSeekTaskParams(query="Python", city="杭州"))
    service.delete_task(pending.id)
    assert repository.get(pending.id) is None

    history = service.create_task(JobSeekTaskParams(query="Agent", city="杭州"))
    repository.set_status(history.id, JobSeekTaskStatus.COMPLETED)

    with pytest.raises(ValueError, match="历史记录"):
        service.delete_task(history.id)
    assert repository.get(history.id).status == JobSeekTaskStatus.COMPLETED


def test_repository_claims_smallest_priority_first(tmp_path: Path):
    service, repository = make_service(tmp_path)
    high_number = service.create_task(
        JobSeekTaskParams(query="Python", city="杭州", priority=50)
    )
    low_number = service.create_task(
        JobSeekTaskParams(query="Agent", city="杭州", priority=10)
    )

    first = repository.claim_next()
    assert first is not None
    assert first.id == low_number.id

    repository.set_status(first.id, JobSeekTaskStatus.COMPLETED)
    second = repository.claim_next()
    assert second is not None
    assert second.id == high_number.id
