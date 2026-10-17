from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.alarm import AttributionOut
from app.models.entity.user import UserEntity
from app.service.overview.alarm_service import AlarmService

router = APIRouter(tags=["overview"])


@router.post("/alarms/{alarm_id}/attribution", response_model=AttributionOut)
async def rerun_attribution(
    alarm_id: str,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AttributionOut:
    return await AlarmService(session, redis).rerun_attribution(alarm_id, user, idempotency_key)
