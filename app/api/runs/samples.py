from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.run import RunSamplesOut
from app.service.runs.run_service import RunService

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}/samples", response_model=RunSamplesOut)
async def run_samples(
    run_id: str,
    since: float | None = None,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RunSamplesOut:
    return await RunService(session).get_samples(run_id, since)
