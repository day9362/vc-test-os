from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm.run import RunOrm, RunSampleOrm


class RunRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def recent_by_machine(self, limit_per_machine: int = 400) -> dict[str, list[bool | None]]:
        rows = (await self.session.execute(select(RunOrm.machine_id, RunOrm.passed, RunOrm.ended_at).order_by(RunOrm.ended_at.desc()).limit(20000))).all()
        grouped: dict[str, list[bool | None]] = {}
        for machine_id, passed, _ended in rows:
            bucket = grouped.setdefault(machine_id, [])
            if len(bucket) < limit_per_machine:
                bucket.append(passed)
        return grouped

    async def recent_rc(self, limit: int = 120) -> list[float]:
        rows = (await self.session.execute(
            select(RunOrm.rc).where(RunOrm.rc.is_not(None)).order_by(RunOrm.ended_at.desc()).limit(limit)
        )).scalars().all()
        return [float(value) for value in rows]

    async def mean_rc_by_machine(self) -> dict[str, list[float]]:
        rows = (await self.session.execute(
            select(RunOrm.machine_id, RunOrm.rc).where(RunOrm.rc.is_not(None)).order_by(RunOrm.ended_at.desc()).limit(20000)
        )).all()
        grouped: dict[str, list[float]] = {}
        for machine_id, rc in rows:
            bucket = grouped.setdefault(machine_id, [])
            if len(bucket) < 120:
                bucket.append(float(rc))
        return grouped

    async def latest_for_slot(self, machine_id: str, slot_index: int, run_id: str | None) -> RunOrm | None:
        if run_id:
            row = await self.session.get(RunOrm, run_id)
            if row is not None:
                return row
        return (await self.session.execute(
            select(RunOrm).where(RunOrm.machine_id == machine_id, RunOrm.slot_index == slot_index).order_by(RunOrm.ended_at.desc()).limit(1)
        )).scalar_one_or_none()

    def _filtered(
        self,
        machine_id: str | None,
        batch_id: str | None,
        passed: bool | None,
        passed_is_null: bool,
        status: str | None,
        q: str | None,
        start: int | None,
        end: int | None,
        exclude_seed: bool = False,
        fleet_ids: list[str] | None = None,
    ) -> Select:
        stmt = select(RunOrm)
        if exclude_seed:
            stmt = stmt.where(RunOrm.batch_id != "B-tb172-seed", ~RunOrm.run_id.like("%-seed"))
        if fleet_ids:
            stmt = stmt.where(RunOrm.machine_id.in_(fleet_ids))
        if machine_id:
            stmt = stmt.where(RunOrm.machine_id == machine_id)
        if batch_id:
            stmt = stmt.where(RunOrm.batch_id == batch_id)
        if passed_is_null:
            if not status:
                stmt = stmt.where(RunOrm.status.in_(("ABORTED", "FAULT")))
            else:
                stmt = stmt.where(RunOrm.passed.is_(None))
        elif passed is True:
            stmt = stmt.where(RunOrm.passed.is_(True), RunOrm.status == "COMPLETED")
        elif passed is False:
            stmt = stmt.where(RunOrm.passed.is_(False), RunOrm.status == "COMPLETED")
        if status:
            stmt = stmt.where(RunOrm.status == status)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(or_(RunOrm.run_id.ilike(pattern), RunOrm.serial_number.ilike(pattern)))
        if start is not None:
            stmt = stmt.where(RunOrm.ended_at >= start)
        if end is not None:
            stmt = stmt.where(RunOrm.ended_at <= end)
        return stmt

    async def page(
        self,
        machine_id: str | None,
        batch_id: str | None,
        passed: bool | None,
        passed_is_null: bool,
        status: str | None,
        q: str | None,
        start: int | None,
        end: int | None,
        cursor: str | None,
        limit: int,
        exclude_seed: bool = False,
        fleet_ids: list[str] | None = None,
    ) -> tuple[list[RunOrm], str | None]:
        stmt = self._filtered(machine_id, batch_id, passed, passed_is_null, status, q, start, end, exclude_seed, fleet_ids)
        if cursor:
            mark_time, mark_id = cursor.split(":", 1)
            stmt = stmt.where(
                (RunOrm.ended_at < int(mark_time))
                | ((RunOrm.ended_at == int(mark_time)) & (RunOrm.run_id < mark_id))
            )
        rows = list(
            (await self.session.execute(stmt.order_by(RunOrm.ended_at.desc(), RunOrm.run_id.desc()).limit(limit + 1))).scalars().all()
        )
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last.ended_at}:{last.run_id}"
            rows = rows[:limit]
        return rows, next_cursor

    async def get(self, run_id: str) -> RunOrm | None:
        return await self.session.get(RunOrm, run_id)

    async def list_for_export(self, batch_id: str | None, start: int | None, end: int | None, exclude_seed: bool = False, fleet_ids: list[str] | None = None) -> list[RunOrm]:
        stmt = self._filtered(None, batch_id, None, False, None, None, start, end, exclude_seed, fleet_ids)
        return list(
            (await self.session.execute(stmt.order_by(RunOrm.ended_at.desc(), RunOrm.run_id.desc()))).scalars().all()
        )

    async def samples(self, run_id: str, since: float | None) -> list[RunSampleOrm]:
        stmt = select(RunSampleOrm).where(RunSampleOrm.run_id == run_id)
        if since is not None:
            stmt = stmt.where(RunSampleOrm.t_s > since)
        stmt = stmt.order_by(RunSampleOrm.t_s)
        return list((await self.session.execute(stmt)).scalars().all())

    async def recent_completed(self, fleet_ids: list[str] | None = None, limit: int = 2000) -> list[RunOrm]:
        stmt = select(RunOrm).where(RunOrm.status == "COMPLETED", RunOrm.keep_result.is_(True)).order_by(RunOrm.ended_at.desc()).limit(limit)
        if fleet_ids:
            stmt = stmt.where(RunOrm.machine_id.in_(fleet_ids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_by_batches(self, batch_ids: list[str], fleet_ids: list[str] | None = None) -> list[RunOrm]:
        if not batch_ids:
            return []
        stmt = select(RunOrm).where(RunOrm.batch_id.in_(batch_ids)).order_by(RunOrm.ended_at.asc())
        if fleet_ids:
            stmt = stmt.where(RunOrm.machine_id.in_(fleet_ids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def search_runs(self, q: str, limit: int) -> list[RunOrm]:
        pattern = f"%{q}%"
        stmt = (
            select(RunOrm)
            .where(or_(RunOrm.run_id.ilike(pattern), RunOrm.serial_number.ilike(pattern), RunOrm.batch_id.ilike(pattern)))
            .order_by(RunOrm.ended_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def search_batches(self, q: str, limit: int) -> list[str]:
        pattern = f"%{q}%"
        stmt = (
            select(RunOrm.batch_id)
            .where(RunOrm.batch_id != "", RunOrm.batch_id.ilike(pattern))
            .distinct()
            .order_by(RunOrm.batch_id)
            .limit(limit)
        )
        return [row for row in (await self.session.execute(stmt)).scalars().all() if row]

    async def search_plans(self, q: str, limit: int) -> list[str]:
        pattern = f"%{q}%"
        stmt = (
            select(RunOrm.plan_id)
            .where(RunOrm.plan_id != "", RunOrm.plan_id.ilike(pattern))
            .distinct()
            .order_by(RunOrm.plan_id)
            .limit(limit)
        )
        return [row for row in (await self.session.execute(stmt)).scalars().all() if row]
