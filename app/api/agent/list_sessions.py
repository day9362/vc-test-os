from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.agent import ModuleName, SessionSummaryOut
from app.models.entity.user import UserEntity
from app.service.agent.sessions import AgentSessionService

router = APIRouter(tags=["agent"])


@router.get("/agent/sessions", response_model=list[SessionSummaryOut])
async def list_sessions(
    module: ModuleName = Query(),
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SessionSummaryOut]:
    rows = await AgentSessionService(session).list_for(user.user_id, module)
    return [SessionSummaryOut(session_id=row.session_id, module=row.module, title=row.title, updated_at=row.updated_at) for row in rows]
