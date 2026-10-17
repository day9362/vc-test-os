from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.models.orm.compensation import CompHistoryOrm


class CompensationRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    def record(self, actor: str, machine_id: str, mode: str, compensation: list, audit_id: str) -> CompHistoryOrm:
        row = CompHistoryOrm(
            id=f"CH-{uuid4().hex[:12]}",
            time=now_ms(),
            actor=actor,
            machine_id=machine_id,
            mode=mode,
            compensation=compensation,
            audit_id=audit_id,
        )
        self.session.add(row)
        return row

    async def page(self, machine_id: str, cursor: str | None, limit: int) -> tuple[list[CompHistoryOrm], str | None]:
        stmt = select(CompHistoryOrm).where(CompHistoryOrm.machine_id == machine_id)
        if cursor:
            mark_time, mark_id = cursor.split(":", 1)
            stmt = stmt.where((CompHistoryOrm.time < int(mark_time)) | ((CompHistoryOrm.time == int(mark_time)) & (CompHistoryOrm.id < mark_id)))
        rows = list((await self.session.execute(stmt.order_by(CompHistoryOrm.time.desc(), CompHistoryOrm.id.desc()).limit(limit + 1))).scalars().all())
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last.time}:{last.id}"
            rows = rows[:limit]
        return rows, next_cursor
