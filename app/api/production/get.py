from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.production import ProductionOut
from app.service.production.service import ProductionService

router = APIRouter(tags=["production"])


@router.get("/production", response_model=ProductionOut | None)
async def get_production(_: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> ProductionOut | None:
    return await ProductionService(session).production()
