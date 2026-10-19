from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.production import StopIn, StopOut
from app.models.entity.user import UserEntity
from app.service.production.service import ProductionService

router = APIRouter(tags=["production"])


@router.post("/production/stop", response_model=StopOut)
async def stop_production(
    body: StopIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StopOut:
    return await ProductionService(session, redis).stop(body.batch_id, user, idempotency_key)
