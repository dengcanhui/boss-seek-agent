from pydantic import BaseModel, Field, field_validator, model_validator


def _clean_keywords(value: list[str] | None) -> list[str] | None:
    """清洗关键词列表：去除空白、空字符串和重复项，同时保持原有顺序。"""
    if value is None:
        return None
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        keyword = item.strip()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        result.append(keyword)
    return result


class GlobalConfig(BaseModel):
    """全局求职执行配置。

    这些规则对所有搜索任务生效，主要用于岗位过滤和浏览器执行节奏控制。
    """

    # 公司名称命中任一关键词时跳过该岗位。
    company_blacklist: list[str] = Field(default_factory=list)
    # 职位名称命中任一关键词时跳过该岗位。
    job_blacklist: list[str] = Field(default_factory=list)
    # 岗位详情描述命中任一关键词时跳过该岗位。
    description_blacklist: list[str] = Field(default_factory=list)
    # 单个搜索任务最多浏览的岗位数量，达到上限后停止继续加载岗位。
    max_jobs_per_task: int = Field(default=100, ge=1, le=1000)
    # 每次打招呼后的随机等待时间下限，单位：秒。
    greet_wait_min_seconds: float = Field(default=8.0, ge=0, le=3600)
    # 每次打招呼后的随机等待时间上限，单位：秒。
    greet_wait_max_seconds: float = Field(default=15.0, ge=0, le=3600)
    # 是否过滤活跃时间中出现“周 / 月 / 年”等长期不活跃特征的岗位。
    filter_inactive_over_week: bool = True

    @field_validator(
        "company_blacklist",
        "job_blacklist",
        "description_blacklist",
        mode="before",
    )
    @classmethod
    def clean_blacklists(cls, value: list[str] | None) -> list[str]:
        return _clean_keywords(value) or []

    @model_validator(mode="after")
    def validate_wait_range(self) -> "GlobalConfig":
        if self.greet_wait_min_seconds > self.greet_wait_max_seconds:
            raise ValueError("greet_wait_min_seconds 不能大于 greet_wait_max_seconds")
        return self


class GlobalConfigUpdate(BaseModel):
    """全局配置的增量更新参数。

    ``None`` 表示保持原值不变；列表传空值表示明确清空对应黑名单。
    """

    company_blacklist: list[str] | None = None
    job_blacklist: list[str] | None = None
    description_blacklist: list[str] | None = None
    max_jobs_per_task: int | None = Field(default=None, ge=1, le=1000)
    greet_wait_min_seconds: float | None = Field(default=None, ge=0, le=3600)
    greet_wait_max_seconds: float | None = Field(default=None, ge=0, le=3600)
    filter_inactive_over_week: bool | None = None

    @field_validator(
        "company_blacklist",
        "job_blacklist",
        "description_blacklist",
        mode="before",
    )
    @classmethod
    def clean_blacklists(cls, value: list[str] | None) -> list[str] | None:
        return _clean_keywords(value)
