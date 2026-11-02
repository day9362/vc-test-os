from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.report import AnalysisOut
from app.service.reports.analysis_service import AnalysisService

router = APIRouter(tags=["reports"])


@router.get("/reports/analysis", response_model=AnalysisOut)
async def report_analysis(
    batch_ids: str = Query(default=""),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    return await AnalysisService(session).build(batch_ids.split(","))
