from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field

from .enums import JobSeekTaskStatus


class BossSearchConfig(BaseModel):
    """一次 BOSS 搜索的可执行参数快照。

    字段名与浏览器请求参数保持一致；这里保存的是已经解析好的 BOSS 参数值，
    不再承担自然语言到 code 的转换职责。
    """

    # 搜索关键词，例如：Agent 开发、Python 后端。
    query: str
    # BOSS 城市 code，例如杭州对应的城市编码。
    city: str
    # 求职类型单选 code；无筛选时为 None。
    jobType: str | None = None
    # 薪资单选 code；无筛选时为 None。
    salary: str | None = None
    # 以下字段均支持多选，保存对应的 BOSS code。
    experience: list[str] = Field(default_factory=list)
    degree: list[str] = Field(default_factory=list)
    industry: list[str] = Field(default_factory=list)
    scale: list[str] = Field(default_factory=list)
    stage: list[str] = Field(default_factory=list)


class JobSeekTaskParams(BaseModel):
    """创建和修改求职任务共用的语义参数。None 表示未提供该字段。"""

    query: str | None = Field(
        default=None,
        description="BOSS 搜索关键词，自由文本，例如 Agent开发、Python后端；不要填写 BOSS code。",
    )
    city: str | None = Field(
        default=None,
        description="具体城市语义名称，例如 杭州；不能填写省份、地区概念或 BOSS code，不确定时先调用 search_boss_options。",
    )
    jobType: str | None = Field(
        default=None,
        description="求职类型单选，只能使用当前 search_parameter_guide.allowed_values.jobType；无要求时为 null。",
    )
    salary: str | None = Field(
        default=None,
        description="薪资档位单选，只能使用当前 search_parameter_guide.allowed_values.salary；不要自行创造薪资区间，无要求时为 null。",
    )
    experience: list[str] | None = Field(
        default=None,
        description="工作经验可多选，只能使用当前 search_parameter_guide.allowed_values.experience 中的语义名称。",
    )
    degree: list[str] | None = Field(
        default=None,
        description="学历可多选，只能使用当前 search_parameter_guide.allowed_values.degree 中的语义名称。",
    )
    industry: list[str] | None = Field(
        default=None,
        description="具体细分行业名称，可多选；不能填写行业组或 BOSS code，不确定时先调用 search_boss_options。",
    )
    scale: list[str] | None = Field(
        default=None,
        description="公司规模可多选，只能使用当前 search_parameter_guide.allowed_values.scale 中的语义名称。",
    )
    stage: list[str] | None = Field(
        default=None,
        description="融资阶段可多选，只能使用当前 search_parameter_guide.allowed_values.stage 中的语义名称。",
    )
    priority: int | None = Field(
        default=None,
        ge=-1000,
        le=1000,
        description="任务优先级，数字越小越优先；用户未指定时可不传。",
    )


class JobSeekTask(BaseModel):
    """一条持久化的求职搜索任务。"""

    id: int
    # 编译后的实际搜索参数。
    config: BossSearchConfig
    # 数值越小越优先执行。
    priority: int
    # pending / running / completed / failed 等任务状态。
    status: JobSeekTaskStatus
    # 最近一次失败原因；正常任务为 None。
    error: str | None = None
    created_at: datetime
    updated_at: datetime
