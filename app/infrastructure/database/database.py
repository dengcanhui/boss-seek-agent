import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)


Migration = Callable[[Connection], None]


def init_db() -> None:
    from . import tables  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _run_migrations()


def _run_migrations() -> None:
    migrations: tuple[tuple[int, Migration], ...] = (
        (1, _migrate_search_task_config_names),
        (2, _migrate_unlimited_search_values),
        (3, _migrate_job_record_not_greeted_reason),
        (5, _migrate_utc_times_to_china),
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, "
                "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        applied = set(
            connection.scalars(text("SELECT version FROM schema_migrations")).all()
        )
        for version, migration in migrations:
            if version in applied:
                continue
            migration(connection)
            connection.execute(
                text("INSERT INTO schema_migrations(version) VALUES (:version)"),
                {"version": version},
            )


def _update_task_config(connection: Connection, task_id: int, data: dict[str, Any]) -> None:
    connection.execute(
        text("UPDATE search_tasks SET config_json = :config_json WHERE id = :task_id"),
        {
            "task_id": task_id,
            "config_json": json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        },
    )


def _migrate_search_task_config_names(connection: Connection) -> None:
    """把旧任务 JSON 字段名迁移成浏览器真实请求参数名。"""
    rename = {
        "keyword": "query",
        "job_type": "jobType",
        "experiences": "experience",
        "degrees": "degree",
        "industries": "industry",
        "scales": "scale",
        "stages": "stage",
    }
    rows = connection.execute(text("SELECT id, config_json FROM search_tasks")).all()
    for task_id, raw in rows:
        data = json.loads(raw)
        changed = False
        for old_name, new_name in rename.items():
            if old_name in data:
                data[new_name] = data.pop(old_name)
                changed = True
        if changed:
            _update_task_config(connection, task_id, data)


def _migrate_job_record_not_greeted_reason(connection: Connection) -> None:
    """为旧版岗位记录表补充未打招呼原因字段。"""
    columns = {column["name"] for column in inspect(connection).get_columns("job_records")}
    if "not_greeted_reason" not in columns:
        connection.execute(text("ALTER TABLE job_records ADD COLUMN not_greeted_reason TEXT"))


def _migrate_utc_times_to_china(connection: Connection) -> None:
    """把旧版按 UTC 保存的 SQLite 业务时间迁移为东八区时间。"""
    if connection.dialect.name != "sqlite":
        return

    table_columns = {
        "search_tasks": ("created_at", "updated_at"),
        "job_records": ("greeted_at", "first_seen_at", "last_seen_at"),
        "candidate_profile": ("updated_at",),
        "global_config": ("updated_at",),
        "chat_messages": ("created_at",),
    }
    inspector = inspect(connection)
    for table, columns in table_columns.items():
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column not in existing:
                continue
            connection.execute(
                text(
                    f'UPDATE "{table}" '
                    f'SET "{column}" = datetime("{column}", "+8 hours") '
                    f'WHERE "{column}" IS NOT NULL'
                )
            )


def _migrate_unlimited_search_values(connection: Connection) -> None:
    """把旧版用字符串 ``0`` 表示的“不限”迁移为当前的空值语义。"""
    rows = connection.execute(text("SELECT id, config_json FROM search_tasks")).all()
    multi_fields = ("experience", "degree", "industry", "scale", "stage")
    for task_id, raw in rows:
        data = json.loads(raw)
        changed = False

        for field in ("jobType", "salary"):
            if data.get(field) == "0":
                data[field] = None
                changed = True

        for field in multi_fields:
            values = data.get(field)
            if isinstance(values, list) and "0" in values:
                data[field] = [value for value in values if value != "0"]
                changed = True

        if changed:
            _update_task_config(connection, task_id, data)
