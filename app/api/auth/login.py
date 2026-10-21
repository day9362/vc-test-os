from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.auth import LoginIn, TokenOut
from app.repo.user_repo import UserRepo
from app.service.auth_service import AuthService
from redis.asyncio import Redis

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session), redis: Redis = Depends(get_redis)) -> TokenOut:
    token = await AuthService(UserRepo(session), redis).login(body.tenant, body.username, body.password)
    return TokenOut(token=token)
