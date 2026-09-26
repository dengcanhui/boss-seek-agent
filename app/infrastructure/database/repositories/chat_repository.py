from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.tables import ChatMessageRow


class ChatRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory: sessionmaker[Session] = session_factory

    def add(self, conversation_id: str, role: str, content: str) -> None:
        with self.session_factory() as session:
            session.add(ChatMessageRow(conversation_id=conversation_id, role=role, content=content))
            session.commit()

    def recent(self, conversation_id: str, limit: int = 30) -> list[dict[str, str]]:
        with self.session_factory() as session:
            stmt = (
                select(ChatMessageRow)
                .where(ChatMessageRow.conversation_id == conversation_id)
                .order_by(ChatMessageRow.id.desc())
                .limit(limit)
            )
            rows = list(reversed(session.scalars(stmt).all()))
            return [{"role": r.role, "content": r.content} for r in rows]

    def list_conversations(self, limit: int = 50) -> list[dict[str, object]]:
        """按最近活动时间返回已有会话；第一条用户消息作为标题。"""
        with self.session_factory() as session:
            stmt = (
                select(
                    ChatMessageRow.conversation_id,
                    func.max(ChatMessageRow.id).label("last_message_id"),
                    func.max(ChatMessageRow.created_at).label("updated_at"),
                )
                .group_by(ChatMessageRow.conversation_id)
                .order_by(func.max(ChatMessageRow.id).desc())
                .limit(limit)
            )
            conversations = session.execute(stmt).all()

            result: list[dict[str, object]] = []
            for row in conversations:
                title_stmt = (
                    select(ChatMessageRow.content)
                    .where(
                        ChatMessageRow.conversation_id == row.conversation_id,
                        ChatMessageRow.role == "user",
                    )
                    .order_by(ChatMessageRow.id.asc())
                    .limit(1)
                )
                title = session.scalar(title_stmt) or "新对话"
                result.append(
                    {
                        "conversation_id": row.conversation_id,
                        "title": title.strip()[:40] or "新对话",
                        "updated_at": row.updated_at,
                    }
                )
            return result
