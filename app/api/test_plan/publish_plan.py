from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.test_plan import PublishIn, PublishOut
from app.models.entity.user import UserEntity
from app.service.test_plan.plan_service import PlanService

router = APIRouter(tags=["plans"])


@router.post("/plans", response_model=PublishOut)
async def publish_plan(
    body: PublishIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PublishOut:
    return await PlanService(session, redis).publish(body, user, idempotency_key)
