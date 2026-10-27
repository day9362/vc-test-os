import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.clock import now_ms
from app.core.config import settings
from app.core.database import SessionLocal, get_session
from app.core.errors import AppError
from app.models.dto.agent import AgentMessageOut, MessageIn
from app.models.entity.user import UserEntity
from app.service.agent.scope import with_scope
from app.service.agent.sessions import AgentSessionService

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
    message = await AgentSessionService(session).send(user.user_id, session_id, text, actor=user.name, model=body.model, batches=body.batches)
    return AgentMessageOut.model_validate(message, from_attributes=True)


@router.post("/agent/sessions/{session_id}/messages/stream")
async def stream_message(
    session_id: str,
    body: MessageIn,
    user: UserEntity = Depends(current_user),
) -> StreamingResponse:
    text = body.text.strip()
    if not text:
        raise AppError(422, "EMPTY_MESSAGE", "请输入内容")
    if not settings.anthropic_base_url or not settings.anthropic_api_key:
        raise AppError(503, "MODEL_NOT_CONFIGURED", "没有配置第三方模型地址或密钥")
    async with SessionLocal() as db:
        module, sdk_session_id = await AgentSessionService(db).prepare(user.user_id, session_id, text)
    outgoing: asyncio.Queue = asyncio.Queue()
    started = now_ms()
    prompt = with_scope(text, body.model, body.batches)

    async def drive() -> None:
        from app.service.agent.runtime import iter_turn

        wrote = False
        try:
            async for event in iter_turn(module, prompt, sdk_session_id):
                turn = event.pop("turn", None) if event.get("type") == "error" else None
                if event.get("type") == "done" or _worth_saving(turn):
                    async with SessionLocal() as db:
                        reply = await AgentSessionService(db).save_reply(
                            user.user_id,
                            session_id,
                            turn or event,
                            actor=user.name,
                            started_ms=started,
                            ok=event.get("type") == "done",
                        )
                    wrote = True
                    if event.get("type") == "done":
                        event = {"type": "done", "message": AgentMessageOut.model_validate(reply, from_attributes=True).model_dump()}
                await outgoing.put(event)
            if not wrote:
                async with SessionLocal() as db:
                    await AgentSessionService(db).record_usage(user.user_id, session_id, None, actor=user.name, started_ms=started, ok=False)
        except Exception:
            if not wrote:
                try:
                    async with SessionLocal() as db:
                        await AgentSessionService(db).record_usage(user.user_id, session_id, None, actor=user.name, started_ms=started, ok=False)
                except Exception:
                    pass
            await outgoing.put({"type": "error", "message": "Agent 没有完成这次对话"})
        finally:
            await outgoing.put(None)

    asyncio.create_task(drive())

    async def generate():
        while True:
            event = await outgoing.get()
            if event is None:
                break
            yield _event(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _worth_saving(turn: dict | None) -> bool:
    if not turn:
        return False
    return bool((turn.get("text") or "").strip() or turn.get("blocks"))


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
