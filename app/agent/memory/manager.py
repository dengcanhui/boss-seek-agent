from typing import TypedDict

from app.application.candidate.candidate_profile_service import CandidateProfileService
from app.domain.candidate.models import CandidateProfile
from app.infrastructure.database.repositories.chat_repository import ChatRepository


class MemoryContext(TypedDict):
    """一次 Agent 调用需要的记忆上下文。"""

    # 当前会话最近的聊天历史，按时间顺序排列。
    history: list[dict[str, str]]
    # 用户长期维护的求职画像。
    profile: CandidateProfile


class MemoryManager:
    def __init__(
        self,
        chat_repository: ChatRepository,
        profile_service: CandidateProfileService,
    ):
        self.chat_repository: ChatRepository = chat_repository
        self.profile_service: CandidateProfileService = profile_service

    def build(self, conversation_id: str, history_limit: int = 30) -> MemoryContext:
        """组装当前会话历史和长期求职画像。"""
        return {
            "history": self.chat_repository.recent(conversation_id, history_limit),
            "profile": self.profile_service.get_profile(),
        }
