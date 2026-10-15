from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.machine import MachineOut
from app.service.overview.machine_service import MachineService

router = APIRouter(tags=["overview"])


@router.get("/machines/{machine_id}", response_model=MachineOut)
async def machine_detail(machine_id: str, _: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> MachineOut:
    return await MachineService(session).get_machine(machine_id)
