from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.database import tables  # noqa: F401
from app.infrastructure.database.database import Base
from app.infrastructure.database.repositories.job_record_repository import JobRecordRepository


def make_repository(tmp_path: Path) -> JobRecordRepository:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'job_records.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return JobRecordRepository(sessionmaker(bind=engine, expire_on_commit=False))


def detail_payload(*, active="刚刚活跃"):
    return {
        "code": 0,
        "zpData": {
            "jobInfo": {
                "encryptId": "job-abc",
                "jobName": "Agent 开发",
                "salaryDesc": "15-25K",
                "locationName": "杭州",
                "postDescription": "负责 Agent 与工具调用平台开发",
            },
            "brandComInfo": {"brandName": "示例科技"},
            "bossInfo": {
                "name": "张先生",
                "title": "技术负责人",
                "activeTimeDesc": active,
            },
            "relationInfo": {"interestJob": False, "beFriend": False},
        },
    }


def test_upsert_job_detail_keeps_one_record_and_counts_visits(tmp_path: Path):
    repository = make_repository(tmp_path)

    first = repository.upsert_detail(detail_payload(), task_id=10)
    second = repository.upsert_detail(detail_payload(active="今日活跃"), task_id=11)

    assert first.id == second.id
    assert second.job_key == "job-abc"
    assert second.last_task_id == 11
    assert second.job_name == "Agent 开发"
    assert second.company_name == "示例科技"
    assert second.description == "负责 Agent 与工具调用平台开发"
    assert second.active_time_desc == "今日活跃"
    assert second.visit_count == 2
    assert second.greeted is False
    summaries = repository.list()
    assert len(summaries) == 1
    assert not hasattr(summaries[0], "detail")
    assert repository.get(second.id).description == "负责 Agent 与工具调用平台开发"


def test_job_key_prefers_real_detail_encrypt_id_over_security_id(tmp_path: Path):
    repository = make_repository(tmp_path)
    payload = detail_payload()
    payload["zpData"]["securityId"] = "request-security-token"

    assert repository.job_key(payload) == "job-abc"


def test_mark_greeted_survives_later_detail_refresh(tmp_path: Path):
    repository = make_repository(tmp_path)
    payload = detail_payload()
    repository.upsert_detail(payload, task_id=10)

    greeted = repository.mark_greeted(payload)
    refreshed = repository.upsert_detail(payload, task_id=12)

    assert greeted.greeted is True
    assert greeted.greeted_at is not None
    assert refreshed.greeted is True
    assert refreshed.greeted_at == greeted.greeted_at
    assert refreshed.visit_count == 2


def test_not_greeted_reason_is_persisted_and_cleared_after_greeting(tmp_path: Path):
    repository = make_repository(tmp_path)
    payload = detail_payload()
    repository.upsert_detail(payload, task_id=10)

    skipped = repository.mark_not_greeted(payload, "职位命中黑名单：销售")
    summary = repository.list()[0]

    assert skipped.not_greeted_reason == "职位命中黑名单：销售"
    assert summary.not_greeted_reason == "职位命中黑名单：销售"

    greeted = repository.mark_greeted(payload)

    assert greeted.greeted is True
    assert greeted.not_greeted_reason is None
