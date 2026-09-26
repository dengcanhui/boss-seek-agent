from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


CHINA_TZ = timezone(timedelta(hours=8))


def china_now() -> datetime:
    """返回东八区当前时间，直接用于数据库时间字段。"""
    return datetime.now(CHINA_TZ)


class JobSeekTaskRow(Base):
    """求职搜索任务的数据库记录。"""

    # 物理表名暂时保留，避免仅因代码命名迁移破坏已有 SQLite 数据。
    __tablename__ = "search_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_json: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=china_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=china_now, onupdate=china_now)


class JobRecordRow(Base):
    """岗位历史记录，用于去重、状态判断和保留岗位详情。"""

    __tablename__ = "job_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    last_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    job_name: Mapped[str] = mapped_column(String(255), default="")
    company_name: Mapped[str] = mapped_column(String(255), default="")
    salary_desc: Mapped[str | None] = mapped_column(String(128), nullable=True)
    location_desc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    boss_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    boss_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active_time_desc: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contacted: Mapped[bool] = mapped_column(Boolean, default=False)
    greeted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # 未打招呼时记录原因，成功打招呼后清空。
    not_greeted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    greeted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visit_count: Mapped[int] = mapped_column(Integer, default=1)
    detail_json: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=china_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=china_now)


class CandidateProfileRow(Base):
    """候选人长期求职画像的单行存储。"""

    __tablename__ = "candidate_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    profile_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=china_now, onupdate=china_now)


class GlobalConfigRow(Base):
    """全局执行配置的单行存储。"""

    __tablename__ = "global_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    config_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=china_now, onupdate=china_now)


class ChatMessageRow(Base):
    """Agent 会话消息记录。"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=china_now)
