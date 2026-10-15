from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.machine import MachineOut, SlotCurveOut
from app.repo.machine_repo import MachineRepo
from app.repo.run_repo import RunRepo
from app.service.overview.mapping import machine_entity, machine_out


class MachineService:
    def __init__(self, session: AsyncSession):
        self.machines = MachineRepo(session)
        self.runs = RunRepo(session)

    async def list_machines(self) -> list[MachineOut]:
        rows = await self.machines.list_with_slots()
        recent = await self.runs.recent_by_machine()
        return [machine_out(machine_entity(machine, slots, recent.get(machine.machine_id, []))) for machine, slots in rows]

    async def get_machine(self, machine_id: str) -> MachineOut:
        found = await self.machines.get_with_slots(machine_id)
        if found is None:
            raise AppError(404, "NOT_FOUND", f"机台 {machine_id} 不存在")
        machine, slots = found
        recent = await self.runs.recent_by_machine()
        return machine_out(machine_entity(machine, slots, recent.get(machine_id, [])))

    async def slot_curve(self, machine_id: str, index: int, since: float | None) -> SlotCurveOut:
        found = await self.machines.get_with_slots(machine_id)
        if found is None:
            raise AppError(404, "NOT_FOUND", f"机台 {machine_id} 不存在")
        _, slots = found
        slot = next((item for item in slots if item.index == index), None)
        run = await self.runs.latest_for_slot(machine_id, index, slot.run_id if slot else None)
        if run is None:
            return SlotCurveOut(run_id=None, plan_id=None, plan_version=None, duration_s=None, points=[], deltas={})
        samples = await self.runs.samples(run.run_id, since)
        deltas = {key: float(value) for key, value in (run.result or {}).get("deltas", {}).items() if isinstance(value, (int, float))}
        duration = (run.result or {}).get("duration_s")
        if duration is None and samples:
            duration = int(samples[-1].t_s)
        return SlotCurveOut(
            run_id=run.run_id,
            plan_id=run.plan_id,
            plan_version=run.plan_version,
            duration_s=duration,
            points=[{"t_s": row.t_s, "T0": row.t0, "T1": row.t1, "Ta": row.ta, "power_w": row.power_w} for row in samples],
            deltas=deltas,
        )
