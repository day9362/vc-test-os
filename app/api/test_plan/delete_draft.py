from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.test_plan import DeleteOut
from app.models.entity.user import UserEntity
from app.service.test_plan.plan_service import PlanService

router = APIRouter(tags=["plans"])


@router.delete("/plan-drafts/{plan_id}", response_model=DeleteOut)
async def delete_draft(
    plan_id: str,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DeleteOut:
    return await PlanService(session, redis).delete_draft(plan_id, user, idempotency_key)
