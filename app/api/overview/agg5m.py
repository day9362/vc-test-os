from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.stats import Agg5mOut
from app.service.overview.stats_service import StatsService

router = APIRouter(tags=["overview"])


@router.get("/stats/agg5m", response_model=list[Agg5mOut])
async def agg5m(
    from_ms: int | None = Query(default=None, alias="from"),
    to_ms: int | None = Query(default=None, alias="to"),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Agg5mOut]:
    return await StatsService(session).agg5m(from_ms, to_ms)
