from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.test_plan import PlanBody, ValidateOut
from app.service.test_plan.plan_service import PlanService

router = APIRouter(tags=["plans"])


@router.post("/plans/validate", response_model=ValidateOut)
async def validate_plan(body: PlanBody, _: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> ValidateOut:
    return await PlanService(session).validate(body)
