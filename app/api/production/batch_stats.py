from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.production import BatchStatPageOut
from app.service.production.service import ProductionService

router = APIRouter(tags=["production"])


@router.get("/batch-stats", response_model=BatchStatPageOut)
async def list_batch_stats(
    state: str | None = None,
    model: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> BatchStatPageOut:
    return await ProductionService(session).batch_stats(state, model, q, cursor, limit)
