from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.service.runs.run_service import RunService

router = APIRouter(tags=["runs"])


@router.get("/export/production.csv")
async def export_production_csv(
    batch_id: str | None = None,
    start: int | None = Query(default=None, alias="from"),
    end: int | None = Query(default=None, alias="to"),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    body = await RunService(session).export_csv(batch_id, start, end)
    return Response(
        content=body.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="production.csv"'},
    )
