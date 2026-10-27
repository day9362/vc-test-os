from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.ai_usage import UsageSummaryOut
from app.service.ai.usage import UsageService

router = APIRouter(tags=["ai"])


@router.get("/ai/usage/summary", response_model=UsageSummaryOut)
async def usage_summary(
    days: int = Query(default=30),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> UsageSummaryOut:
    return await UsageService(session).summary(days)
