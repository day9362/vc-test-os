from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.production import PrecheckOut, ProductionIn
from app.service.production.service import ProductionService

router = APIRouter(tags=["production"])


@router.post("/production/precheck", response_model=PrecheckOut)
async def precheck(
    body: ProductionIn,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> PrecheckOut:
    return await ProductionService(session).precheck_body(body)
