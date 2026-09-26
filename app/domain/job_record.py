from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobRecordSummary(BaseModel):
    """岗位历史记录摘要。

    用于列表展示、去重和判断岗位是否已经访问或打过招呼，不包含完整岗位详情。
    """

    id: int
    # BOSS 岗位的稳定唯一标识，用于跨任务去重。
    job_key: str
    # 最近一次发现该岗位的求职任务 ID。
    last_task_id: int | None = None
    job_name: str
    company_name: str
    salary_desc: str | None = None
    location_desc: str | None = None
    boss_name: str | None = None
    boss_title: str | None = None
    # 招聘者在 BOSS 页面展示的活跃时间文本。
    active_time_desc: str | None = None
    # 是否曾与招聘者建立过沟通。
    contacted: bool = False
    # 是否已经执行过打招呼动作。
    greeted: bool = False
    # 未打招呼时记录具体原因；成功打招呼后会清空。
    not_greeted_reason: str | None = None
    greeted_at: datetime | None = None
    # 该岗位被搜索任务重复看到的次数。
    visit_count: int
    first_seen_at: datetime
    last_seen_at: datetime


class JobRecord(JobRecordSummary):
    """包含完整详情数据的岗位记录。"""

    description: str | None = None
    # BOSS 岗位详情接口的结构化原始数据，保留未单独建模的字段。
    detail: dict[str, Any]
