from app.agent.tools.decorator import agent_tool
from app.domain.candidate.models import CandidateProfile
from app.infrastructure.database.repositories.profile_repository import CandidateProfileRepository


class CandidateProfileService:
    def __init__(self, repository: CandidateProfileRepository):
        self.repository: CandidateProfileRepository = repository

    @agent_tool(description="读取用户长期求职画像。")
    def get_profile(self) -> CandidateProfile:
        return self.repository.load()

    @agent_tool(
        description=(
            "增量更新用户长期求职画像（未传字段不改）。"
            "实际已有技能、学历和工作经验属于候选人属性；期望城市/岗位属于职业目标。"
            "与招聘平台检索条件有关的偏好写search_preferences；"
            "双休、出差、夜班、加班等需要阅读岗位描述才能判断的要求写job_preferences。"
            "用户说'必须/一定要/不接受'的写job_preferences.required；"
            "说'希望/最好/优先'的写job_preferences.preferred。"
            "不要把岗位招聘要求误认为候选人已有技能，也不要把临时搜索条件当长期偏好。"
            "嵌套required或preferred只传需要修改的字段；传空列表表示清空该类要求。"
        )
    )
    def update_profile(self, changes: CandidateProfile) -> CandidateProfile:
        current = self.repository.load()
        patch = changes.model_dump(exclude_unset=True)
        merged = current.model_dump()
        for field, value in patch.items():
            if field == "job_preferences":
                # 嵌套子字段分别更新：只传 required 不会擦除 preferred。
                # 显式传 {} 则重置整个 job_preferences。
                merged[field] = {**merged[field], **value} if value else {}
            else:
                # 其他字段沿用整体替换语义；空列表/空字典代表清空。
                merged[field] = value
        updated = CandidateProfile.model_validate(merged)
        return self.repository.save(updated)
