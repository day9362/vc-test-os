from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.test_plan import PlanItemOut
from app.service.test_plan.plan_service import PlanService

router = APIRouter(tags=["plans"])


@router.get("/plans", response_model=list[PlanItemOut])
async def list_plans(_: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> list[PlanItemOut]:
    return await PlanService(session).list_plans()
