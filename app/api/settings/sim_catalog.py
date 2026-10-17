from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.settings import FaultCatalogOut, ScenarioListOut
from app.service.settings.settings_service import SettingsService

router = APIRouter(tags=["settings"])


@router.get("/sim/scenarios", response_model=ScenarioListOut)
async def list_scenarios(_: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> ScenarioListOut:
    return await SettingsService(session).list_scenarios()


@router.get("/sim/fault-catalog", response_model=FaultCatalogOut)
async def list_faults(_: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> FaultCatalogOut:
    return await SettingsService(session).list_faults()
