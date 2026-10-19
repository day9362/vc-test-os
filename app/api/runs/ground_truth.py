from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.run import RunGroundTruthOut
from app.service.runs.run_service import RunService

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}/ground-truth", response_model=RunGroundTruthOut)
async def run_ground_truth(
    run_id: str,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RunGroundTruthOut:
    return await RunService(session).get_ground_truth(run_id)
