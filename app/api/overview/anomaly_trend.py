from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.stats import AnomalyTrendOut
from app.service.overview.stats_service import StatsService

router = APIRouter(tags=["overview"])


@router.get("/stats/anomaly-trend", response_model=AnomalyTrendOut)
async def anomaly_trend(
    hours: int = Query(default=8),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnomalyTrendOut:
    return await StatsService(session).anomaly_trend(hours)
