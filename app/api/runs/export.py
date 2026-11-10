from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.service.runs.run_service import RunService

router = APIRouter(tags=["runs"])


@router.get("/export/production")
async def export_production(
    limits_plan_id: str,
    version: int | None = None,
    batch_id: str | None = None,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await RunService(session).export_with_limits(limits_plan_id, version, batch_id)


@router.get("/export/production.csv")
async def export_production_csv(
    batch_id: list[str] = Query(default_factory=list),
    start: int | None = Query(default=None, alias="from"),
    end: int | None = Query(default=None, alias="to"),
    group: str = "day",
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    body, media, filename = await RunService(session).export_csv(batch_id, start, end, group)
    return _file(body, media, filename)


@router.get("/export/products.csv")
async def export_products(
    run_id: list[str] = Query(default_factory=list),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    body, media, filename = await RunService(session).export_products(run_id)
    return _file(body, media, filename)


@router.get("/export/raw")
async def export_raw(
    run_id: list[str] = Query(default_factory=list),
    batch_id: str | None = None,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    body, media, filename = await RunService(session).export_raw(run_id, batch_id)
    return _file(body, media, filename)


def _file(body: bytes, media: str, filename: str) -> Response:
    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"},
    )
