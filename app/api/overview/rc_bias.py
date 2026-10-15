from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.stats import RcBiasOut
from app.service.overview.stats_service import StatsService

router = APIRouter(tags=["overview"])


@router.get("/stats/rc-bias", response_model=RcBiasOut)
async def rc_bias(_: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> RcBiasOut:
    return await StatsService(session).rc_bias()
