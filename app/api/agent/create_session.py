from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.agent import CreateSessionIn, SessionOut, session_out
from app.models.entity.user import UserEntity
from app.service.agent.sessions import AgentSessionService

router = APIRouter(tags=["agent"])


@router.post("/agent/sessions", response_model=SessionOut)
async def create_session(
    body: CreateSessionIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    created = await AgentSessionService(session).create(user.user_id, body.module)
    return session_out(created, [])
