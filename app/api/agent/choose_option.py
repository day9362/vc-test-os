from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.agent import ChoiceIn, ChoicesBlock
from app.models.entity.user import UserEntity
from app.service.agent.sessions import AgentSessionService

router = APIRouter(tags=["agent"])


@router.post("/agent/sessions/{session_id}/choices/{choice_id}", response_model=ChoicesBlock)
async def choose_option(
    session_id: str,
    choice_id: str,
    body: ChoiceIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ChoicesBlock:
    saved = await AgentSessionService(session).choose(user.user_id, session_id, choice_id, body.index)
    return ChoicesBlock.model_validate(saved)
