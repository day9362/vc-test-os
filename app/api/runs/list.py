from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.run import RunPageOut
from app.service.runs.run_service import RunService

router = APIRouter(tags=["runs"])


@router.get("/runs", response_model=RunPageOut)
async def list_runs(
    machine_id: str | None = None,
    batch_id: str | None = None,
    passed: str | None = None,
    status: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50),
    start: int | None = Query(default=None, alias="from"),
    end: int | None = Query(default=None, alias="to"),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RunPageOut:
    return await RunService(session).list_runs(machine_id, batch_id, passed, status, q, start, end, cursor, limit)
