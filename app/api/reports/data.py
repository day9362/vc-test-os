from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.report import ReportDataOut
from app.service.reports.report_service import ReportService

router = APIRouter(tags=["reports"])


@router.get("/reports/data", response_model=ReportDataOut)
async def report_data(
    batch_ids: str = Query(default=""),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ReportDataOut:
    return await ReportService(session).data(batch_ids)
