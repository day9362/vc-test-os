from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.compensation import HistoryPageOut
from app.service.compensation.compensation_service import CompensationService

router = APIRouter(tags=["compensation"])


@router.get("/machines/{machine_id}/compensation/history", response_model=HistoryPageOut)
async def compensation_history(
    machine_id: str,
    cursor: str | None = None,
    limit: int = Query(default=50),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HistoryPageOut:
    return await CompensationService(session).list_history(machine_id, cursor, limit)
