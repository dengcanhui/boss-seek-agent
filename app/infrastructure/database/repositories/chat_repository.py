from sqlalchemy import select
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
