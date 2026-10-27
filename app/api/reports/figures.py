import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import SessionLocal, get_session
from app.core.errors import AppError
from app.models.dto.report import FigureCreatedOut, FigureIn, FigureOut
from app.models.entity.user import UserEntity
from app.models.orm.report_figure import ReportFigureOrm
from app.service.reports.figures import FigureService, execute_figure
from app.service.reports.store import reports_dir

router = APIRouter(tags=["reports"])


@router.post("/reports/figures", response_model=FigureCreatedOut)
async def create_figure(
    body: FigureIn,
    background: BackgroundTasks,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FigureCreatedOut:
    created = await FigureService(session).create(body.batch_ids, body.prompt, user)
    background.add_task(execute_figure, created.figure_id, user.name)
    return created


@router.get("/reports/figures", response_model=list[FigureOut])
async def list_figures(
    batch_ids: str = Query(default=""),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[FigureOut]:
    return await FigureService(session).list_for(batch_ids)


@router.get("/reports/figures/{figure_id}.png")
async def figure_png(
    figure_id: str,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    row = await session.get(ReportFigureOrm, figure_id)
    if row is None or not row.png_name:
        raise AppError(404, "NOT_FOUND", "这张图没有 PNG")
    path = reports_dir() / row.png_name
    if not path.exists():
        raise AppError(404, "NOT_FOUND", "这张图没有 PNG")
    return FileResponse(path, media_type="image/png")


@router.get("/reports/figures/{figure_id}", response_model=FigureOut)
async def get_figure(
    figure_id: str,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FigureOut:
    return await FigureService(session).get(figure_id)


@router.delete("/reports/figures/{figure_id}", status_code=204)
async def delete_figure(
    figure_id: str,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await FigureService(session).delete(figure_id)


@router.get("/reports/figures/{figure_id}/events")
async def figure_events(figure_id: str, _: object = Depends(current_user)) -> StreamingResponse:
    return StreamingResponse(_events(figure_id), media_type="text/event-stream")


async def _events(figure_id: str):
    seen = ""
    for _ in range(400):
        async with SessionLocal() as session:
            row = await session.get(ReportFigureOrm, figure_id)
        if row is None:
            yield _event({"step": "done"})
            return
        if row.step and row.step != seen:
            seen = row.step
            yield _event({"step": row.step})
        if row.status in {"done", "failed"}:
            yield _event({"step": "done"})
            return
        await asyncio.sleep(0.5)
    yield _event({"step": "done"})


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
