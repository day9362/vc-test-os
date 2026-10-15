from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.alarm import AckAllOut
from app.models.entity.user import UserEntity
from app.service.overview.alarm_service import AlarmService

router = APIRouter(tags=["overview"])


@router.post("/alarms/ack-all", response_model=AckAllOut)
async def ack_all(
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AckAllOut:
    return await AlarmService(session, redis).acknowledge_all(user, idempotency_key)
