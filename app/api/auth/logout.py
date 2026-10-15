from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from app.api.deps import bearer_token
from app.core.database import get_session
from app.core.redis import get_redis
from app.repo.user_repo import UserRepo
from app.service.auth_service import AuthService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["auth"])


@router.post("/auth/logout", status_code=204)
async def logout(
    token: str = Depends(bearer_token),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> None:
    await AuthService(UserRepo(session), redis).logout(token)
