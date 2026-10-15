from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.machine import SlotCurveOut
from app.service.overview.machine_service import MachineService

router = APIRouter(tags=["overview"])


@router.get("/machines/{machine_id}/slots/{index}/curve", response_model=SlotCurveOut)
async def slot_curve(
    machine_id: str,
    index: int,
    since: float | None = None,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SlotCurveOut:
    return await MachineService(session).slot_curve(machine_id, index, since)
