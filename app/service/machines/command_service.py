import json

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.errors import AppError
from app.models.dto.machine import MachineActionOut
from app.models.entity.user import UserEntity
from app.models.orm.machine import MachineOrm, SlotOrm
from app.models.orm.run import RunOrm
from app.repo.audit_repo import AuditRepo
from app.repo.machine_repo import MachineRepo
from app.service.machines.cluster import post_cluster
from app.service.overview.hub import hub
from app.service.overview.machine_service import MachineService


class MachineCommandService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.redis = redis
        self.machines = MachineRepo(session)
        self.audit = AuditRepo(session)

    async def power_on(self, machine_id: str, user: UserEntity, idempotency_key: str | None) -> MachineActionOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return MachineActionOut.model_validate(cached)
        machine, slots = await self._require_online(machine_id)
        if machine.status == "FAULT":
            raise AppError(409, "CONFLICT", f"{machine_id} 处于故障，请先复位")
        if machine.status == "MAINTENANCE":
            raise AppError(409, "CONFLICT", f"{machine_id} 正在维修")
        upstream = await post_cluster(f"/machines/{machine_id}/power-on", None)
        machine.status = str((upstream or {}).get("status") or "READY")
        machine.last_sync_at = now_ms()
        return await self._finish(machine, slots, user, idempotency_key, "machine.power_on", {})

    async def power_off(self, machine_id: str, user: UserEntity, idempotency_key: str | None) -> MachineActionOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return MachineActionOut.model_validate(cached)
        machine, slots = await self._require_online(machine_id)
        await post_cluster(f"/machines/{machine_id}/power-off", None)
        await self._abort_sampling(slots)
        machine.status = "OFFLINE"
        machine.last_sync_at = now_ms()
        return await self._finish(machine, slots, user, idempotency_key, "machine.power_off", {})

    async def _require_online(self, machine_id: str) -> tuple[MachineOrm, list[SlotOrm]]:
        found = await self.machines.get_with_slots(machine_id)
        if found is None:
            raise AppError(404, "NOT_FOUND", f"机台 {machine_id} 不存在")
        machine, slots = found
        if machine.comm_status == "DISCONNECTED":
            raise AppError(503, "MACHINE_DISCONNECTED", f"{machine_id} 通信断开，未转发给集群")
        return machine, slots

    async def _abort_sampling(self, slots: list[SlotOrm]) -> None:
        stamp = now_ms()
        for slot in slots:
            if slot.phase != "SAMPLING":
                continue
            if slot.run_id:
                run = await self.session.get(RunOrm, slot.run_id)
                if run is not None and run.status == "RUNNING":
                    run.status = "ABORTED"
                    run.passed = None
                    run.ended_at = stamp
            slot.phase = "IDLE"
            slot.progress = 0
            slot.power_w = 0
            slot.run_id = None

    async def _finish(self, machine: MachineOrm, slots: list[SlotOrm], user: UserEntity, key: str | None, action: str, request: dict) -> MachineActionOut:
        audit_id = self.audit.record(user.user_id, action, machine.machine_id, request, {"status": machine.status})
        await self.session.commit()
        body = MachineActionOut(audit_id=audit_id, machine_id=machine.machine_id, status=machine.status)
        await self._publish(machine.machine_id)
        await self._store(key, body)
        return body

    async def _publish(self, machine_id: str) -> None:
        machine = await MachineService(self.session).get_machine(machine_id)
        summary = machine.model_dump()
        slots = summary.pop("slots")
        summary.pop("capability", None)
        await hub.publish("fleet", [summary])
        await hub.publish("slots", {"machine_id": machine_id, "slots": slots})

    async def _cached(self, key: str | None):
        if not key or self.redis is None:
            return None
        raw = await self.redis.get(f"idem:{key}")
        return json.loads(raw) if raw else None

    async def _store(self, key: str | None, body: MachineActionOut) -> None:
        if not key or self.redis is None:
            return
        await self.redis.set(f"idem:{key}", body.model_dump_json(), ex=600)
