from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.audit import AuditItemOut, AuditPageOut
from app.models.orm.alarm import AuditOrm
from app.repo.audit_repo import AuditRepo


class AuditService:
    def __init__(self, session: AsyncSession):
        self.audit = AuditRepo(session)

    async def page(
        self,
        actor: str | None,
        machine_id: str | None,
        start: int | None,
        end: int | None,
        cursor: str | None,
        limit: int,
    ) -> AuditPageOut:
        if limit < 1 or limit > 500:
            raise AppError(400, "BAD_REQUEST", "limit 需要在 1 到 500 之间")
        if cursor and ":" not in cursor:
            raise AppError(400, "BAD_REQUEST", "cursor 格式不正确")
        rows, next_cursor = await self.audit.page(actor, machine_id, start, end, cursor, limit)
        return AuditPageOut(items=[_item(row) for row in rows], next_cursor=next_cursor)


def _item(row: AuditOrm) -> AuditItemOut:
    return AuditItemOut(
        audit_id=row.audit_id,
        time=row.time,
        actor=row.actor,
        action=row.action,
        machine_id=row.machine_id or "",
        request=row.request or {},
        result=row.result or {},
    )
