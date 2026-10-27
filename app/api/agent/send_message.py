from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.core.errors import AppError
from app.models.dto.agent import AgentMessageOut, MessageIn
from app.models.entity.user import UserEntity
from app.service.agent.sessions import store

router = APIRouter(tags=["agent"])


@router.post("/agent/sessions/{session_id}/messages", response_model=AgentMessageOut)
async def send_message(session_id: str, body: MessageIn, user: UserEntity = Depends(current_user)) -> AgentMessageOut:
    text = body.text.strip()
    if not text:
        raise AppError(422, "EMPTY_MESSAGE", "请输入内容")
    message = await store.send(user.user_id, session_id, text)
    return AgentMessageOut.model_validate(message, from_attributes=True)
