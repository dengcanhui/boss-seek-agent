from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.database import tables  # noqa: F401
from app.infrastructure.database.database import Base
from app.infrastructure.database.repositories.chat_repository import ChatRepository


def test_list_conversations_uses_first_user_message_as_title_and_latest_order(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'chat.db'}")
    Base.metadata.create_all(engine)
    repository = ChatRepository(sessionmaker(bind=engine))

    repository.add("older", "user", "杭州 Agent 岗位")
    repository.add("older", "assistant", "好的")
    repository.add("newer", "user", "上海 Python 岗位")
    repository.add("newer", "assistant", "收到")

    conversations = repository.list_conversations()

    assert [item["conversation_id"] for item in conversations] == ["newer", "older"]
    assert conversations[0]["title"] == "上海 Python 岗位"
    assert conversations[1]["title"] == "杭州 Agent 岗位"


def test_recent_only_returns_requested_conversation(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'chat.db'}")
    Base.metadata.create_all(engine)
    repository = ChatRepository(sessionmaker(bind=engine))

    repository.add("a", "user", "第一轮")
    repository.add("b", "user", "另一个会话")
    repository.add("a", "assistant", "第一轮回复")

    assert repository.recent("a") == [
        {"role": "user", "content": "第一轮"},
        {"role": "assistant", "content": "第一轮回复"},
    ]
