from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.ai_usage import AiCallPageOut
from app.service.ai.usage import UsageService

router = APIRouter(tags=["ai"])


@router.get("/ai/calls", response_model=AiCallPageOut)
async def ai_calls(
    module: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AiCallPageOut:
    return await UsageService(session).calls(module, cursor, limit)
