from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.stats import KpiOut
from app.service.overview.stats_service import StatsService

router = APIRouter(tags=["overview"])


@router.get("/stats/kpi", response_model=KpiOut)
async def kpi(
    range: str = Query(default="shift"),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> KpiOut:
    return await StatsService(session).kpi(range)
