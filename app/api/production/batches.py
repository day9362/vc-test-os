from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.production import BatchOut
from app.service.production.service import ProductionService

router = APIRouter(tags=["production"])


@router.get("/batches", response_model=list[BatchOut])
async def list_batches(_: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> list[BatchOut]:
    return await ProductionService(session).batches()
