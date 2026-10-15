from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.alarm import AlarmActionOut
from app.models.entity.user import UserEntity
from app.service.overview.alarm_service import AlarmService
from app.service.overview.hub import hub

router = APIRouter(tags=["overview"])


@router.post("/alarms/{alarm_id}/unack", response_model=AlarmActionOut)
async def unack_alarm(
    alarm_id: str,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AlarmActionOut:
    body = await AlarmService(session, redis).unacknowledge(alarm_id, user, idempotency_key)
    await hub.publish("alarms", body.alarm.model_dump())
    return body
