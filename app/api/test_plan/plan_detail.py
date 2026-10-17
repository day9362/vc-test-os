from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.test_plan import PlanItemOut
from app.service.test_plan.plan_service import PlanService

router = APIRouter(tags=["plans"])


@router.get("/plans/{plan_id}", response_model=PlanItemOut)
async def get_plan(
    plan_id: str,
    version: int | None = Query(default=None),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> PlanItemOut:
    return await PlanService(session).get_plan(plan_id, version)
