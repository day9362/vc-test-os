from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.report import ReportNarrativeOut, ReportSummaryIn
from app.models.entity.user import UserEntity
from app.service.reports.report_service import ReportService

router = APIRouter(tags=["reports"])


@router.post("/reports/summary", response_model=ReportNarrativeOut)
async def report_summary(
    body: ReportSummaryIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ReportNarrativeOut:
    return await ReportService(session).summary(body.batch_ids, user)
