from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .enums import JobSeekTaskStatus


# 以下值直接进入 Tool Calling 的 JSON Schema（语义名称，不是 BOSS code）。
# code 的映射依旧由 BossSearchConfigCompiler 从 data/search_options.json 读取。
JobTypeName = Literal["不限", "全职", "兼职"]
SalaryName = Literal["不限", "3K以下", "3-5K", "5-10K", "10-20K", "20-50K", "50K以上"]
ExperienceName = Literal[
    "不限", "在校生", "应届生", "经验不限",
    "1年以内", "1-3年", "3-5年", "5-10年", "10年以上",
]
DegreeName = Literal["不限", "初中及以下", "中专/中技", "高中", "大专", "本科", "硕士", "博士"]
ScaleName = Literal[
    "不限", "0-20人", "20-99人", "100-499人",
    "500-999人", "1000-9999人", "10000人以上",
]
StageName = Literal[
    "不限", "未融资", "天使轮", "A轮", "B轮",
    "C轮", "D轮及以上", "已上市", "不需要融资",
]


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
    """创建/修改搜索任务的语义参数。

    枚举使用 BOSS 选项的中文名称；None 表示未提供该条件。
    对修改任务而言，显式 null / [] / "不限" 可用于取消筛选。
    城市和行业选项较多，仍通过 search_boss_options 查询。
    """

    query: str | None = Field(
        default=None,
        description="BOSS 搜索关键词，自由文本，例如Agent开发、Python后端；不传BOSS code。",
    )
    city: str | None = Field(
        default=None,
        description=(
            "具体城市名称，例如杭州；不能填写省份、地区概念或BOSS code。"
            "不确定是否合法或需要查询地区时，调用 search_boss_options(field='city', keyword=...)，"
            "再使用返回的name。"
        ),
    )
    jobType: JobTypeName | None = Field(
        default=None,
        description="求职类型，单选；无要求可省略或填null，修改时也可以填'不限'清空。",
    )
    salary: SalaryName | None = Field(
        default=None,
        description="BOSS 薪资档位，单选；必须选枚举里的完整区间名称，不能编造区间。无要求填null或'不限'。",
    )
    experience: list[ExperienceName] | None = Field(
        default=None,
        description="工作经验筛选，可多选枚举中的中文名称。无要求填null或空列表；'经验不限'是平台的可选档位。",
    )
    degree: list[DegreeName] | None = Field(
        default=None,
        description="学历筛选，可多选枚举中的中文名称。无要求填null或空列表。",
    )
    industry: list[str] | None = Field(
        default=None,
        description=(
            "具体细分行业名称，可多选；不能填写行业组或BOSS code。"
            "不确定时调用 search_boss_options(field='industry', keyword=...)，"
            "然后使用返回的name；无要求填null或空列表。"
        ),
    )
    scale: list[ScaleName] | None = Field(
        default=None,
        description="公司规模筛选，可多选枚举里的中文名称；无要求填null或空列表。",
    )
    stage: list[StageName] | None = Field(
        default=None,
        description="公司融资阶段筛选，可多选枚举里的中文名称；无要求填null或空列表。",
    )
    priority: int | None = Field(
        default=None,
        ge=-1000,
        le=1000,
        description="任务优先级，数字越小越优先执行；用户未指定时可不传。",
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
    # 任务结束或失败的原因；自然完成时为 None。
    reason: str | None = None
    visited_count: int | None = None
    greeted_count: int | None = None
    created_at: datetime
    updated_at: datetime
