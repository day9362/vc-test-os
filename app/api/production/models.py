from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.production import ProductModelOut
from app.service.production.service import ProductionService

router = APIRouter(tags=["production"])


@router.get("/models", response_model=list[ProductModelOut])
async def list_models(_: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> list[ProductModelOut]:
    return await ProductionService(session).models()
