from pydantic import BaseModel, Field


class JobPreferences(BaseModel):
    """无法通过招聘平台搜索筛选项表达、需要结合岗位详情判断的长期偏好。

    required 是硬性要求：不满足或岗位描述无法确认时，不自动打招呼。
    preferred 是软性偏好：不满足时不直接拒绝岗位。
    """

    required: list[str] = Field(
        default_factory=list,
        description=(
            "用户对岗位的必须条件；不满足或岗位未明确说明时不自动打招呼。"
            "例如：必须双休、不接受大小周、不接受出差、不能上夜班。"
            "仅记录用户明确表示'必须'、'一定要'、'只接受'、'不接受'等硬性要求。"
            "每条要求独立保存，禁止把相反语义合并到同一条。"
        ),
    )
    preferred: list[str] = Field(
        default_factory=list,
        description=(
            "用户对岗位的非强制偏好；不满足也不直接拒绝岗位。"
            "例如：希望少加班、最好离家近、优先远程办公。"
            "用户表达'最好'、'优先'、'希望'等非强制要求时写入。"
        ),
    )


class CandidateProfile(BaseModel):
    """候选人的长期求职画像，也作为画像增量更新参数使用。

    用于 Agent 理解稳定偏好，不代表某次搜索的即时筛选条件。
    未传字段保持不变；显式空列表可清空对应内容。
    job_preferences 支持对 required/preferred 分别增量修改。
    """

    expected_cities: list[str] = Field(
        default_factory=list,
        description="长期期望工作的城市名称，如杭州、上海；不要写省份代码或搜索任务临时城市。",
    )
    expected_jobs: list[str] = Field(
        default_factory=list,
        description="长期期望的岗位方向，如Agent开发、Python后端；不是当前岗位的职位名称。",
    )
    skills: list[str] = Field(
        default_factory=list,
        description="候选人已经掌握的技能关键词；不要把招聘岗位提到的技术当作候选人已有技能。",
    )
    experience_years: float | None = Field(
        default=None,
        ge=0,
        description="候选人累计实际工作年限，单位年，可为2.5；不要把招聘要求的年限填到这里。",
    )
    degree: str | None = Field(
        default=None,
        description="候选人的最高学历，如本科、硕士；不要填入岗位招聘学历要求。",
    )
    expected_salary: str | None = Field(
        default=None,
        description="用户长期期望的薪资范围，保留原始语义，如15-20K；不是单条岗位薪资。",
    )
    company_preferences: dict[str, object] = Field(
        default_factory=dict,
        description=(
            "用户对公司行业、规模、融资阶段或性质等的长期偏好；"
            "例如偏好国企、大型企业。与休息制度、出差等岗位要求区分。"
        ),
    )
    search_preferences: dict[str, object] = Field(
        default_factory=dict,
        description=(
            "仅保存与BOSS招聘平台搜索任务参数和搜索策略有关的长期偏好。"
            "双休、单休、加班、出差、夜班等搜索框无法直接筛选的要求，"
            "应该写入job_preferences而不是这里。"
        ),
    )
    job_preferences: JobPreferences = Field(
        default_factory=JobPreferences,
        description=(
            "需要读取岗位详情才能判断的长期要求。"
            "required记录必须满足的硬性条件，preferred记录可以不满足的软性偏好。"
            "例如'必须双休'写入required，'最好不加班'写入preferred。"
            "本次仅更新一类时不要清空另一类。"
        ),
    )
