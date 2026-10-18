from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.machine import PlanHistoryOut
from app.service.machines.plan_history import PlanHistoryService

router = APIRouter(tags=["machines"])


@router.get("/machines/{machine_id}/plan-history", response_model=PlanHistoryOut)
async def plan_history(
    machine_id: str,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> PlanHistoryOut:
    return await PlanHistoryService(session).history(machine_id)
