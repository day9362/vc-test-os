from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm.alarm import AlarmOrm, AttributionOrm


class AlarmRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _filtered(self, acked: bool | None, machine_id: str | None, level: str | None) -> Select:
        stmt = select(AlarmOrm)
        if acked is not None:
            stmt = stmt.where(AlarmOrm.acked == acked)
        if machine_id:
            stmt = stmt.where(AlarmOrm.machine_id == machine_id)
        if level:
            stmt = stmt.where(AlarmOrm.level == level)
        return stmt

    async def page(self, acked: bool | None, machine_id: str | None, level: str | None, cursor: str | None, limit: int) -> tuple[list[AlarmOrm], str | None]:
        stmt = self._filtered(acked, machine_id, level)
        if cursor:
            mark_time, mark_id = cursor.split(":", 1)
            stmt = stmt.where((AlarmOrm.time < int(mark_time)) | ((AlarmOrm.time == int(mark_time)) & (AlarmOrm.id < mark_id)))
        rows = list((await self.session.execute(stmt.order_by(AlarmOrm.time.desc(), AlarmOrm.id.desc()).limit(limit + 1))).scalars().all())
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last.time}:{last.id}"
            rows = rows[:limit]
        return rows, next_cursor

    async def get(self, alarm_id: str) -> AlarmOrm | None:
        return await self.session.get(AlarmOrm, alarm_id)

    async def open_alarms(self) -> list[AlarmOrm]:
        return list((await self.session.execute(select(AlarmOrm).where(AlarmOrm.acked.is_(False)))).scalars().all())

    async def since(self, start: int) -> list[AlarmOrm]:
        return list((await self.session.execute(select(AlarmOrm).where(AlarmOrm.time >= start))).scalars().all())

    async def attribution(self, alarm_id: str) -> AttributionOrm | None:
        return await self.session.get(AttributionOrm, alarm_id)
