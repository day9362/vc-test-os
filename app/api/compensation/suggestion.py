from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.compensation import SuggestionOut
from app.service.compensation.compensation_service import CompensationService

router = APIRouter(tags=["compensation"])


@router.get("/machines/{machine_id}/compensation/suggestion", response_model=SuggestionOut)
async def suggestion(
    machine_id: str,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SuggestionOut:
    return await CompensationService(session).suggestion(machine_id)
