from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.audit import AuditPageOut
from app.service.audit_service import AuditService

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=AuditPageOut)
async def list_audit(
    actor: str | None = None,
    machine_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50),
    start: int | None = Query(default=None, alias="from"),
    end: int | None = Query(default=None, alias="to"),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AuditPageOut:
    return await AuditService(session).page(actor, machine_id, start, end, cursor, limit)
