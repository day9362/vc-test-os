from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session as db_session
from app.models.dto.agent import SessionOut, session_out
from app.models.entity.user import UserEntity
from app.service.agent.sessions import AgentSessionService

router = APIRouter(tags=["agent"])


@router.get("/agent/sessions/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> SessionOut:
    row, messages = await AgentSessionService(session).get(user.user_id, session_id)
    return session_out(row, messages)


@router.delete("/agent/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> Response:
    await AgentSessionService(session).delete(user.user_id, session_id)
    return Response(status_code=204)
