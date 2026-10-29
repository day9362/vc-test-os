from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.agent import ActionBlock, ActionDecisionIn
from app.models.entity.user import UserEntity
from app.service.agent.sessions import AgentSessionService

router = APIRouter(tags=["agent"])


@router.post("/agent/sessions/{session_id}/actions/{action_id}", response_model=ActionBlock)
async def decide_action(
    session_id: str,
    action_id: str,
    body: ActionDecisionIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ActionBlock:
    saved = await AgentSessionService(session).decide(user.user_id, session_id, action_id, body.decision)
    return ActionBlock.model_validate(saved)
