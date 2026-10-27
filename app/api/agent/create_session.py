from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.models.dto.agent import CreateSessionIn, SessionOut, session_out
from app.models.entity.user import UserEntity
from app.service.agent.sessions import store

router = APIRouter(tags=["agent"])


@router.post("/agent/sessions", response_model=SessionOut)
async def create_session(body: CreateSessionIn, user: UserEntity = Depends(current_user)) -> SessionOut:
    return session_out(store.create(user.user_id, body.module))
