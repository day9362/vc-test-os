from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.production import BatchStatOut
from app.service.production.service import ProductionService

router = APIRouter(tags=["production"])


@router.get("/batch-stats/{batch_id}", response_model=BatchStatOut)
async def get_batch_stat(
    batch_id: str,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> BatchStatOut:
    return await ProductionService(session).batch_stat(batch_id)
