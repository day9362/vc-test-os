from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.stats import PipelineOut
from app.service.overview.stats_service import StatsService

router = APIRouter(tags=["overview"])


@router.get("/stats/pipeline", response_model=PipelineOut)
async def pipeline(_: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> PipelineOut:
    return await StatsService(session).pipeline()
