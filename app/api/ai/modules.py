from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.ai_usage import AiModuleOut
from app.service.ai.usage import UsageService

router = APIRouter(tags=["ai"])


@router.get("/ai/modules", response_model=list[AiModuleOut])
async def ai_modules(
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AiModuleOut]:
    return await UsageService(session).modules()
