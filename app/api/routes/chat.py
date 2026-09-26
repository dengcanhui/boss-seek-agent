from fastapi import APIRouter, HTTPException
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


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest, agent: AgentDep):
    try:
        reply = await agent.run(body.conversation_id, body.message)
        return ChatResponse(reply=reply)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
