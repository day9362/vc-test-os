from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.models.dto.auth import MeOut
from app.models.entity.user import UserEntity

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=MeOut)
async def me(user: UserEntity = Depends(current_user)) -> MeOut:
    return MeOut(user_id=user.user_id, name=user.name, role=user.role)
