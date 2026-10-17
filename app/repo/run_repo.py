from sqlalchemy import or_, select
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

    async def samples(self, run_id: str, since: float | None) -> list[RunSampleOrm]:
        stmt = select(RunSampleOrm).where(RunSampleOrm.run_id == run_id)
        if since is not None:
            stmt = stmt.where(RunSampleOrm.t_s > since)
        stmt = stmt.order_by(RunSampleOrm.t_s)
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
