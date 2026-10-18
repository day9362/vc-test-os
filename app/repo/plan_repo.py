from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm.plan import PlanDispatchOrm
from app.models.orm.run import RunOrm


class PlanRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def history(self, machine_id: str) -> list[PlanDispatchOrm]:
        rows = (await self.session.execute(
            select(PlanDispatchOrm).where(PlanDispatchOrm.machine_id == machine_id).order_by(PlanDispatchOrm.started_at.desc())
        )).scalars().all()
        return list(rows)

    async def run_count(self, machine_id: str, plan_id: str, version: int, started_at: int, ended_at: int | None) -> int:
        stmt = select(func.count()).select_from(RunOrm).where(
            RunOrm.machine_id == machine_id,
            RunOrm.plan_id == plan_id,
            RunOrm.plan_version == version,
            RunOrm.ended_at >= started_at,
        )
        if ended_at is not None:
            stmt = stmt.where(RunOrm.ended_at < ended_at)
        return int((await self.session.execute(stmt)).scalar_one())
