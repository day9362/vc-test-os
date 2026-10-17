from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm.machine import MachineOrm, SlotOrm


class MachineRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_with_slots(self) -> list[tuple[MachineOrm, list[SlotOrm]]]:
        machines = (await self.session.execute(select(MachineOrm).order_by(MachineOrm.machine_id))).scalars().all()
        slots = (await self.session.execute(select(SlotOrm).order_by(SlotOrm.index))).scalars().all()
        grouped: dict[str, list[SlotOrm]] = {}
        for slot in slots:
            grouped.setdefault(slot.machine_id, []).append(slot)
        return [(machine, grouped.get(machine.machine_id, [])) for machine in machines]

    async def get_with_slots(self, machine_id: str) -> tuple[MachineOrm, list[SlotOrm]] | None:
        machine = await self.session.get(MachineOrm, machine_id)
        if machine is None:
            return None
        slots = (await self.session.execute(
            select(SlotOrm).where(SlotOrm.machine_id == machine_id).order_by(SlotOrm.index)
        )).scalars().all()
        return machine, list(slots)

    async def search(self, q: str, limit: int) -> list[MachineOrm]:
        pattern = f"%{q}%"
        stmt = (
            select(MachineOrm)
            .where(or_(MachineOrm.machine_id.ilike(pattern), MachineOrm.serial.ilike(pattern)))
            .order_by(MachineOrm.machine_id)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
