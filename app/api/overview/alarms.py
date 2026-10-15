from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.alarm import AlarmPageOut
from app.models.entity.user import UserEntity
from app.service.overview.alarm_service import AlarmService

router = APIRouter(tags=["overview"])


@router.get("/alarms", response_model=AlarmPageOut)
async def list_alarms(
    acked: bool | None = None,
    machine_id: str | None = None,
    level: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50),
    _: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AlarmPageOut:
    return await AlarmService(session).list_alarms(acked, machine_id, level, cursor, limit)
