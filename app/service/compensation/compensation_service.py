from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.errors import AppError
from app.models.dto.compensation import ChannelBiasOut, CompChannelOut, CompensationOut
from app.repo.machine_repo import MachineRepo
from app.service.compensation.bias import estimate_channel_bias
from app.service.compensation.cluster import cluster_json


class CompensationService:
    def __init__(self, session: AsyncSession):
        self.machines = MachineRepo(session)

    async def channel_bias(self, machine_id: str) -> ChannelBiasOut:
        found = await self.machines.get_with_slots(machine_id)
        if found is None:
            raise AppError(404, "NOT_FOUND", f"机台 {machine_id} 不存在")
        return estimate_channel_bias(machine_id, now_ms())

    async def get_compensation(self, machine_id: str) -> CompensationOut:
        await self._require(machine_id)
        payload = await cluster_json("GET", f"/machines/{machine_id}/compensation")
        items = payload if isinstance(payload, list) else payload.get("channels") or payload.get("items") or payload.get("compensation") or []
        return CompensationOut(items=[CompChannelOut(channel=str(row.get("channel") or ""), value=float(row.get("value") or 0)) for row in items if isinstance(row, dict)])

    async def _require(self, machine_id: str):
        found = await self.machines.get_with_slots(machine_id)
        if found is None:
            raise AppError(404, "NOT_FOUND", f"机台 {machine_id} 不存在")
        return found
