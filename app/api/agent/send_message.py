from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.clock import now_ms
from app.core.config import settings
from app.core.database import get_session
from app.core.errors import AppError
from app.models.dto.agent import AgentMessageOut, MessageIn
from app.models.entity.user import UserEntity
from app.service.agent.sessions import store
from app.service.ai.usage import UsageService

router = APIRouter(tags=["agent"])


@router.post("/agent/sessions/{session_id}/messages", response_model=AgentMessageOut)
async def send_message(
    session_id: str,
    body: MessageIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentMessageOut:
    text = body.text.strip()
    if not text:
        raise AppError(422, "EMPTY_MESSAGE", "请输入内容")
    module = store.get(user.user_id, session_id).module
    started = now_ms()
    try:
        message = await store.send(user.user_id, session_id, text)
    except AppError as exc:
        await UsageService(session).record(
            module=module,
            user=user.name,
            model=settings.anthropic_model or "agent",
            input_tokens=0,
            output_tokens=0,
            latency_ms=max(now_ms() - started, 1),
            ok=False,
            ref={"session_id": session_id, "code": exc.code},
        )
        await session.commit()
        raise
    tokens = message.tokens or [0, 0]
    await UsageService(session).record(
        module=module,
        user=user.name,
        model=settings.anthropic_model or "agent",
        input_tokens=tokens[0] if tokens else 0,
        output_tokens=tokens[1] if len(tokens) > 1 else 0,
        latency_ms=max(now_ms() - started, 1),
        ok=True,
        ref={"session_id": session_id},
    )
    await session.commit()
    return AgentMessageOut.model_validate(message, from_attributes=True)
