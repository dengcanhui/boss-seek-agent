from app.agent.tools.decorator import agent_tool
from app.domain.candidate.models import CandidateProfile
from app.infrastructure.database.repositories.profile_repository import CandidateProfileRepository


class CandidateProfileService:
    def __init__(self, repository: CandidateProfileRepository):
        self.repository: CandidateProfileRepository = repository

    @agent_tool(description="读取用户长期求职画像。")
    def get_profile(self) -> CandidateProfile:
        return self.repository.load()

    @agent_tool(description="更新用户长期求职画像。只写入对未来求职长期有价值的信息。")
    def update_profile(self, changes: CandidateProfile) -> CandidateProfile:
        current = self.repository.load()
        updated = current.model_copy(
            update=changes.model_dump(exclude_unset=True),
        )
        return self.repository.save(updated)
