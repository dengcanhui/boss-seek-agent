from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import AgentDep

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """聊天接口请求参数。"""

    # 会话标识；同一会话内的消息会串行处理并共享历史上下文。
    conversation_id: str = Field(default="default", min_length=1, max_length=128)
    # 用户本轮输入内容。
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    """聊天接口返回结果。"""

    # Agent 最终生成的回复文本。
    reply: str


class ChatMessage(BaseModel):
    """单条聊天记录。"""

    role: str
    content: str


class ConversationSummary(BaseModel):
    """聊天会话摘要。"""

    conversation_id: str
    title: str
    updated_at: datetime | None = None


@router.get("/conversations", response_model=list[ConversationSummary])
def conversations(
    agent: AgentDep,
    limit: int = Query(default=50, ge=1, le=100),
):
    return agent.list_conversations(limit)


@router.get("", response_model=list[ChatMessage])
def chat_history(
    agent: AgentDep,
    conversation_id: str = Query(default="default", min_length=1, max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
):
    return agent.list_messages(conversation_id, limit)


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest, agent: AgentDep):
    try:
        reply = await agent.run(body.conversation_id, body.message)
        return ChatResponse(reply=reply)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
