from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.models.dto.agent import SessionOut, session_out
from app.models.entity.user import UserEntity
from app.service.agent.sessions import store

router = APIRouter(tags=["agent"])


@router.get("/agent/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, user: UserEntity = Depends(current_user)) -> SessionOut:
    return session_out(store.get(user.user_id, session_id))
