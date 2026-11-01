from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.production import BatchCreateIn, BatchCreateOut
from app.models.entity.user import UserEntity
from app.service.production.batch_service import BatchCommandService

router = APIRouter(tags=["production"])


@router.post("/batches", response_model=BatchCreateOut)
async def create_batch(
    body: BatchCreateIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> BatchCreateOut:
    return await BatchCommandService(session, redis).create(body, user, idempotency_key)
