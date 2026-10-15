from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.machine import MachineOut
from app.service.overview.machine_service import MachineService

router = APIRouter(tags=["overview"])


@router.get("/machines", response_model=list[MachineOut])
async def list_machines(_: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> list[MachineOut]:
    return await MachineService(session).list_machines()
