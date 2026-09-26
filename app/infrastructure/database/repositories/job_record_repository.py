from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only, sessionmaker

from app.domain.job_record import JobRecord, JobRecordSummary
from app.infrastructure.database.tables import JobRecordRow


class JobRecordRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory: sessionmaker[Session] = session_factory

    @staticmethod
    def _dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @classmethod
    def job_key(cls, detail: dict[str, Any]) -> str:
        data = cls._dict(detail.get("zpData"))
        job_info = cls._dict(data.get("jobInfo"))
        for value in (
            job_info.get("encryptId"),
            job_info.get("encryptJobId"),
            data.get("encryptJobId"),
            job_info.get("jobId"),
            data.get("jobId"),
        ):
            if value not in (None, ""):
                return str(value)

        brand_info = cls._dict(data.get("brandComInfo"))
        boss_info = cls._dict(data.get("bossInfo"))
        identity = "|".join(
            str(value or "")
            for value in (
                job_info.get("jobName"),
                brand_info.get("brandName"),
                job_info.get("salaryDesc"),
                job_info.get("locationName"),
                boss_info.get("name") or boss_info.get("bossName"),
            )
        )
        if not identity.strip("|"):
            identity = json.dumps(detail, ensure_ascii=False, sort_keys=True)
        return "fallback:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @classmethod
    def _values(cls, detail: dict[str, Any]) -> dict[str, Any]:
        data = cls._dict(detail.get("zpData"))
        job_info = cls._dict(data.get("jobInfo"))
        brand_info = cls._dict(data.get("brandComInfo"))
        boss_info = cls._dict(data.get("bossInfo"))
        relation = cls._dict(data.get("relationInfo"))

        return {
            "job_name": str(job_info.get("jobName") or ""),
            "company_name": str(brand_info.get("brandName") or ""),
            "salary_desc": job_info.get("salaryDesc") or job_info.get("salary"),
            "location_desc": (
                job_info.get("locationName")
                or job_info.get("jobArea")
                or job_info.get("address")
            ),
            "description": job_info.get("postDescription"),
            "boss_name": boss_info.get("name") or boss_info.get("bossName"),
            "boss_title": boss_info.get("title") or boss_info.get("bossTitle"),
            "active_time_desc": boss_info.get("activeTimeDesc"),
            "contacted": bool(
                relation.get("interestJob") is True or relation.get("beFriend") is True
            ),
            "detail_json": json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
        }

    CHINA_TZ = timezone(timedelta(hours=8))

    @classmethod
    def _as_china_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=cls.CHINA_TZ)
        return value.astimezone(cls.CHINA_TZ)

    @classmethod
    def _summary_values(cls, row: JobRecordRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "job_key": row.job_key,
            "last_task_id": row.last_task_id,
            "job_name": row.job_name,
            "company_name": row.company_name,
            "salary_desc": row.salary_desc,
            "location_desc": row.location_desc,
            "boss_name": row.boss_name,
            "boss_title": row.boss_title,
            "active_time_desc": row.active_time_desc,
            "contacted": row.contacted,
            "greeted": row.greeted,
            "not_greeted_reason": row.not_greeted_reason,
            "greeted_at": cls._as_china_time(row.greeted_at),
            "visit_count": row.visit_count,
            "first_seen_at": cls._as_china_time(row.first_seen_at),
            "last_seen_at": cls._as_china_time(row.last_seen_at),
        }

    @classmethod
    def _to_summary(cls, row: JobRecordRow) -> JobRecordSummary:
        return JobRecordSummary(**cls._summary_values(row))

    @classmethod
    def _to_domain(cls, row: JobRecordRow) -> JobRecord:
        return JobRecord(
            **cls._summary_values(row),
            description=row.description,
            detail=json.loads(row.detail_json),
        )

    def upsert_detail(self, detail: dict[str, Any], task_id: int | None = None) -> JobRecord:
        key = self.job_key(detail)
        values = self._values(detail)
        now = datetime.now(self.CHINA_TZ)

        with self.session_factory() as session:
            row = session.scalar(select(JobRecordRow).where(JobRecordRow.job_key == key))
            if row is None:
                row = JobRecordRow(
                    job_key=key,
                    last_task_id=task_id,
                    first_seen_at=now,
                    last_seen_at=now,
                    visit_count=1,
                    **values,
                )
                session.add(row)
            else:
                row.last_task_id = task_id
                row.last_seen_at = now
                row.visit_count += 1
                for field, value in values.items():
                    if field == "contacted":
                        row.contacted = bool(row.contacted) or bool(value)
                    elif field != "detail_json" and value in (None, ""):
                        continue
                    else:
                        setattr(row, field, value)
            session.commit()
            session.refresh(row)
            return self._to_domain(row)

    def mark_greeted(self, detail: dict[str, Any]) -> JobRecord:
        key = self.job_key(detail)
        now = datetime.now(self.CHINA_TZ)
        with self.session_factory() as session:
            row = session.scalar(select(JobRecordRow).where(JobRecordRow.job_key == key))
            if row is None:
                values = self._values(detail)
                row = JobRecordRow(
                    job_key=key,
                    greeted=True,
                    greeted_at=now,
                    first_seen_at=now,
                    last_seen_at=now,
                    visit_count=1,
                    **values,
                )
                session.add(row)
            else:
                row.greeted = True
                row.not_greeted_reason = None
                if row.greeted_at is None:
                    row.greeted_at = now
            session.commit()
            session.refresh(row)
            return self._to_domain(row)

    def mark_not_greeted(self, detail: dict[str, Any], reason: str) -> JobRecord:
        """记录本次未打招呼原因。已成功打过招呼的岗位不会被覆盖。"""
        key = self.job_key(detail)
        with self.session_factory() as session:
            row = session.scalar(select(JobRecordRow).where(JobRecordRow.job_key == key))
            if row is None:
                values = self._values(detail)
                row = JobRecordRow(
                    job_key=key,
                    not_greeted_reason=reason,
                    **values,
                )
                session.add(row)
            elif not row.greeted:
                row.not_greeted_reason = reason
            session.commit()
            session.refresh(row)
            return self._to_domain(row)

    def list(self, limit: int = 100) -> list[JobRecordSummary]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(JobRecordRow)
                .options(
                    load_only(
                        JobRecordRow.id,
                        JobRecordRow.job_key,
                        JobRecordRow.last_task_id,
                        JobRecordRow.job_name,
                        JobRecordRow.company_name,
                        JobRecordRow.salary_desc,
                        JobRecordRow.location_desc,
                        JobRecordRow.boss_name,
                        JobRecordRow.boss_title,
                        JobRecordRow.active_time_desc,
                        JobRecordRow.contacted,
                        JobRecordRow.greeted,
                        JobRecordRow.not_greeted_reason,
                        JobRecordRow.greeted_at,
                        JobRecordRow.visit_count,
                        JobRecordRow.first_seen_at,
                        JobRecordRow.last_seen_at,
                    )
                )
                .order_by(JobRecordRow.last_seen_at.desc())
                .limit(limit)
            ).all()
            return [self._to_summary(row) for row in rows]

    def get(self, record_id: int) -> JobRecord | None:
        with self.session_factory() as session:
            row = session.get(JobRecordRow, record_id)
            return self._to_domain(row) if row is not None else None
