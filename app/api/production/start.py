from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.production import ProductionIn, StartOut
from app.models.entity.user import UserEntity
from app.service.production.service import ProductionService

router = APIRouter(tags=["production"])


@router.post("/production/start", response_model=StartOut)
async def start_production(
    body: ProductionIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StartOut:
    return await ProductionService(session, redis).start(body, user, idempotency_key)
