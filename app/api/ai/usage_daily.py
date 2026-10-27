from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.ai_usage import UsageDayOut
from app.service.ai.usage import UsageService

router = APIRouter(tags=["ai"])


@router.get("/ai/usage/daily", response_model=list[UsageDayOut])
async def usage_daily(
    days: int = Query(default=30),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[UsageDayOut]:
    return await UsageService(session).daily(days)
