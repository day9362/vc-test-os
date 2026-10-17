from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.errors import AppError
from app.models.dto.compensation import ChannelBiasOut
from app.repo.machine_repo import MachineRepo
from app.service.compensation.bias import estimate_channel_bias


class CompensationService:
    def __init__(self, session: AsyncSession):
        self.machines = MachineRepo(session)

    async def channel_bias(self, machine_id: str) -> ChannelBiasOut:
        found = await self.machines.get_with_slots(machine_id)
        if found is None:
            raise AppError(404, "NOT_FOUND", f"机台 {machine_id} 不存在")
        return estimate_channel_bias(machine_id, now_ms())
