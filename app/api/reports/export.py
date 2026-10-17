from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.report import ReportExportIn, ReportExportOut
from app.models.entity.user import UserEntity
from app.service.reports.report_service import ReportService

router = APIRouter(tags=["reports"])


@router.post("/reports/export", response_model=ReportExportOut)
async def export_report(
    body: ReportExportIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ReportExportOut:
    return await ReportService(session, redis).export(body, user, idempotency_key)
