from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import AppError
from app.core.redis import get_redis
from app.models.entity.user import UserEntity
from app.repo.user_repo import UserRepo
from app.service.auth_service import AuthService

bearer = HTTPBearer(auto_error=False)


def auth_service(session: AsyncSession = Depends(get_session), redis: Redis = Depends(get_redis)) -> AuthService:
    return AuthService(UserRepo(session), redis)


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    service: AuthService = Depends(auth_service),
) -> UserEntity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "UNAUTHORIZED", "未登录")
    return await service.current_user(credentials.credentials)


def bearer_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "UNAUTHORIZED", "未登录")
    return credentials.credentials
