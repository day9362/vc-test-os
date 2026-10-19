from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.run import RunDetailOut
from app.service.runs.run_service import RunService

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def run_detail(run_id: str, _: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> RunDetailOut:
    return await RunService(session).get_run(run_id)
