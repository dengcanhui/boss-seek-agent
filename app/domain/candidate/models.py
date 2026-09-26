from pydantic import BaseModel, Field


class CandidateProfile(BaseModel):
    """候选人的长期求职画像，也作为画像增量更新参数使用。

    这些信息用于 Agent 理解用户的稳定偏好，不代表某一次搜索任务的即时筛选条件。
    增量更新时通过 ``model_dump(exclude_unset=True)`` 仅提取本次显式传入的字段；
    未传字段保持不变，显式传入空列表或空字典表示清空对应内容。
    """

    # 期望工作的城市名称，例如：杭州、上海。
    expected_cities: list[str] = Field(default_factory=list)
    # 期望岗位方向，例如：Agent 开发、Python 后端。
    expected_jobs: list[str] = Field(default_factory=list)
    # 候选人的核心技能关键词。
    skills: list[str] = Field(default_factory=list)
    # 工作经验年限，允许小数，例如 2.5 年。
    experience_years: float | None = None
    # 最高学历的语义名称，例如：本科。
    degree: str | None = None
    # 期望薪资描述，保留用户原始语义，例如：15-20K。
    expected_salary: str | None = None
    # 对公司行业、规模、融资阶段等公司的长期偏好。
    company_preferences: dict[str, object] = Field(default_factory=dict)
    # 其他与搜索策略相关的长期偏好。
    search_preferences: dict[str, object] = Field(default_factory=dict)
