from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.test_plan import DraftOut, PlanBody
from app.models.entity.user import UserEntity
from app.service.test_plan.plan_service import PlanService

router = APIRouter(tags=["plans"])


@router.post("/plan-drafts", response_model=DraftOut)
async def create_draft(
    body: PlanBody,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DraftOut:
    return await PlanService(session, redis).create_draft(body, user, idempotency_key)
