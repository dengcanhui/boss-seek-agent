from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from app.domain.search.enums import JobSeekTaskStatus
from app.domain.search.models import BossSearchConfig, JobSeekTask
from app.infrastructure.database.tables import JobSeekTaskRow


class JobSeekTaskRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory: sessionmaker[Session] = session_factory

    CHINA_TZ = timezone(timedelta(hours=8))

    @classmethod
    def _as_china_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=cls.CHINA_TZ)
        return value.astimezone(cls.CHINA_TZ)

    @classmethod
    def _to_domain(cls, row: JobSeekTaskRow) -> JobSeekTask:
        return JobSeekTask(
            id=row.id,
            config=BossSearchConfig.model_validate_json(row.config_json),
            priority=row.priority,
            status=JobSeekTaskStatus(row.status),
            error=row.error,
            created_at=cls._as_china_time(row.created_at),
            updated_at=cls._as_china_time(row.updated_at),
        )

    def list(self, statuses: list[JobSeekTaskStatus] | None = None, limit: int = 100) -> list[JobSeekTask]:
        with self.session_factory() as session:
            stmt = select(JobSeekTaskRow)
            if statuses:
                stmt = stmt.where(JobSeekTaskRow.status.in_([s.value for s in statuses]))
                active_statuses = {JobSeekTaskStatus.PENDING, JobSeekTaskStatus.RUNNING}
                if set(statuses).issubset(active_statuses):
                    stmt = stmt.order_by(
                        JobSeekTaskRow.priority.asc(),
                        JobSeekTaskRow.created_at.asc(),
                    )
                else:
                    stmt = stmt.order_by(JobSeekTaskRow.updated_at.desc())
            else:
                stmt = stmt.order_by(JobSeekTaskRow.updated_at.desc())
            stmt = stmt.limit(limit)
            return [self._to_domain(row) for row in session.scalars(stmt).all()]

    def get(self, task_id: int) -> JobSeekTask | None:
        with self.session_factory() as session:
            row = session.get(JobSeekTaskRow, task_id)
            return self._to_domain(row) if row else None

    def create(self, config: BossSearchConfig, priority: int) -> JobSeekTask:
        with self.session_factory() as session:
            row = JobSeekTaskRow(
                config_json=config.model_dump_json(),
                priority=priority,
                status=JobSeekTaskStatus.PENDING.value,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._to_domain(row)

    def update_if_current(
        self,
        task_id: int,
        expected: JobSeekTaskStatus,
        *,
        config: BossSearchConfig | None = None,
        priority: int | None = None,
    ) -> JobSeekTask:
        values: dict[str, object] = {"updated_at": datetime.now(self.CHINA_TZ)}
        if config is not None:
            values["config_json"] = config.model_dump_json()
        if priority is not None:
            values["priority"] = priority
        with self.session_factory() as session:
            session.execute(
                update(JobSeekTaskRow)
                .where(
                    JobSeekTaskRow.id == task_id,
                    JobSeekTaskRow.status == expected.value,
                )
                .values(**values)
            )
            session.commit()
            row = session.get(JobSeekTaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            return self._to_domain(row)

    def set_status(self, task_id: int, status: JobSeekTaskStatus, error: str | None = None) -> JobSeekTask:
        with self.session_factory() as session:
            row = session.get(JobSeekTaskRow, task_id)
            if not row:
                raise KeyError(task_id)
            row.status = status.value
            row.error = error
            row.updated_at = datetime.now(self.CHINA_TZ)
            session.commit()
            session.refresh(row)
            return self._to_domain(row)

    def set_status_if_current(
        self,
        task_id: int,
        expected: JobSeekTaskStatus,
        status: JobSeekTaskStatus,
        error: str | None = None,
    ) -> JobSeekTask:
        with self.session_factory() as session:
            session.execute(
                update(JobSeekTaskRow)
                .where(
                    JobSeekTaskRow.id == task_id,
                    JobSeekTaskRow.status == expected.value,
                )
                .values(
                    status=status.value,
                    error=error,
                    updated_at=datetime.now(self.CHINA_TZ),
                )
            )
            session.commit()
            row = session.get(JobSeekTaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            return self._to_domain(row)

    def recover_running_as_stopped(self) -> int:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(JobSeekTaskRow)
                    .where(JobSeekTaskRow.status == JobSeekTaskStatus.RUNNING.value)
                    .values(
                        status=JobSeekTaskStatus.STOPPED.value,
                        error=None,
                        updated_at=datetime.now(self.CHINA_TZ),
                    )
                ),
            )
            session.commit()
            return int(result.rowcount or 0)

    def delete_if_current(
        self,
        task_id: int,
        expected: JobSeekTaskStatus,
    ) -> bool:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    delete(JobSeekTaskRow).where(
                        JobSeekTaskRow.id == task_id,
                        JobSeekTaskRow.status == expected.value,
                    )
                ),
            )
            session.commit()
            return result.rowcount == 1

    def claim_next(self) -> JobSeekTask | None:
        """原子抢占优先级数值最小的 pending 求职任务。"""
        with self.session_factory() as session:
            while True:
                task_id = session.scalar(
                    select(JobSeekTaskRow.id)
                    .where(JobSeekTaskRow.status == JobSeekTaskStatus.PENDING.value)
                    .order_by(JobSeekTaskRow.priority.asc(), JobSeekTaskRow.created_at.asc())
                    .limit(1)
                )
                if task_id is None:
                    return None

                result = cast(
                    CursorResult[Any],
                    session.execute(
                        update(JobSeekTaskRow)
                        .where(
                            JobSeekTaskRow.id == task_id,
                            JobSeekTaskRow.status == JobSeekTaskStatus.PENDING.value,
                        )
                        .values(
                            status=JobSeekTaskStatus.RUNNING.value,
                            error=None,
                            updated_at=datetime.now(self.CHINA_TZ),
                        )
                    ),
                )
                if result.rowcount == 1:
                    session.commit()
                    row = session.get(JobSeekTaskRow, task_id)
                    if row is None:
                        raise KeyError(task_id)
                    return self._to_domain(row)
                session.rollback()
