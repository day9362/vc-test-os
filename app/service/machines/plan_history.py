from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.errors import AppError
from app.models.dto.machine import PlanHistoryOut, PlanUseOut
from app.repo.machine_repo import MachineRepo
from app.repo.plan_repo import PlanRepo

NAMES = {
    "PLAN-592bbc46": "45度测3分钟",
    "PLAN-3f2c71d0": "HVP 3.5W 标准测试",
}


class PlanHistoryService:
    def __init__(self, session: AsyncSession):
        self.machines = MachineRepo(session)
        self.plans = PlanRepo(session)

    async def history(self, machine_id: str) -> PlanHistoryOut:
        found = await self.machines.get_with_slots(machine_id)
        if found is None:
            raise AppError(404, "NOT_FOUND", f"机台 {machine_id} 不存在")
        machine, _slots = found
        rows = await self.plans.history(machine_id)
        if not rows and machine.plan_id and machine.plan_version is not None:
            rows = [self._open(machine_id, machine.plan_id, machine.plan_version)]
        items = []
        for row in rows:
            items.append(PlanUseOut(
                plan_id=row.plan_id,
                name=row.name,
                version=row.version,
                started_at=row.started_at,
                to=row.ended_at,
                runs=await self.plans.run_count(row.machine_id, row.plan_id, row.version, row.started_at, row.ended_at),
            ))
        return PlanHistoryOut(items=items)

    def _open(self, machine_id: str, plan_id: str, version: int):
        from app.models.orm.plan import PlanDispatchOrm

        return PlanDispatchOrm(
            machine_id=machine_id,
            plan_id=plan_id,
            name=NAMES.get(plan_id, plan_id),
            version=version,
            started_at=now_ms() - 5 * 3_600_000,
            ended_at=None,
        )
