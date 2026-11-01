from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.test_plan import DispatchIn, DispatchOut
from app.models.entity.user import UserEntity
from app.service.test_plan.dispatch import DispatchService

router = APIRouter(tags=["plans"])


@router.post("/plans/dispatch", response_model=DispatchOut)
async def dispatch_plan(
    body: DispatchIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DispatchOut:
    return await DispatchService(session, redis).dispatch(body, user, idempotency_key)
