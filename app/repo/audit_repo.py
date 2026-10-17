from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.models.orm.alarm import AuditOrm


class AuditRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _filtered(self, actor: str | None, machine_id: str | None, start: int | None, end: int | None) -> Select:
        stmt = select(AuditOrm)
        if actor:
            stmt = stmt.where(AuditOrm.actor == actor)
        if machine_id:
            stmt = stmt.where(AuditOrm.machine_id == machine_id)
        if start is not None:
            stmt = stmt.where(AuditOrm.time >= start)
        if end is not None:
            stmt = stmt.where(AuditOrm.time <= end)
        return stmt

    async def page(
        self,
        actor: str | None,
        machine_id: str | None,
        start: int | None,
        end: int | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[AuditOrm], str | None]:
        stmt = self._filtered(actor, machine_id, start, end)
        if cursor:
            mark_time, mark_id = cursor.split(":", 1)
            stmt = stmt.where((AuditOrm.time < int(mark_time)) | ((AuditOrm.time == int(mark_time)) & (AuditOrm.audit_id < mark_id)))
        rows = list((await self.session.execute(stmt.order_by(AuditOrm.time.desc(), AuditOrm.audit_id.desc()).limit(limit + 1))).scalars().all())
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last.time}:{last.audit_id}"
            rows = rows[:limit]
        return rows, next_cursor

    def record(self, actor: str, action: str, machine_id: str, request: dict, result: dict) -> str:
        audit_id = f"AUD-{uuid4().hex[:12]}"
        self.session.add(AuditOrm(
            audit_id=audit_id,
            time=now_ms(),
            actor=actor,
            action=action,
            machine_id=machine_id,
            request=request,
            result=result,
        ))
        return audit_id
