from app.core.clock import now_ms
from app.core.errors import AppError
from app.models.dto.machine import SlotActionOut
from app.models.entity.user import UserEntity
from app.models.orm.machine import MachineOrm, SlotOrm
from app.models.orm.run import RunOrm
from app.service.machines.cluster import post_cluster
from app.service.machines.command_service import MachineCommandService

FREE_PHASES = {"IDLE", "COMPLETED"}


class SlotCommandService(MachineCommandService):
    async def load(self, machine_id: str, index: int, serial_number: str, user: UserEntity, idempotency_key: str | None) -> SlotActionOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return SlotActionOut.model_validate(cached)
        serial = serial_number.strip()
        if not serial:
            raise AppError(422, "VALIDATION_ERROR", "参数校验失败", {"issues": [{"field": "serial_number", "message": "serial_number 不能为空"}]})
        machine, slot = await self._slot(machine_id, index)
        self._require_ready(machine)
        if slot.phase not in FREE_PHASES:
            raise AppError(409, "CONFLICT", f"{machine_id} 的 {index} 号槽正在使用，不能装板")
        await post_cluster(f"/machines/{machine_id}/slots/{index}/load", {"serial_number": serial})
        slot.serial_number = serial
        slot.last_error = ""
        slot.progress = 0
        return await self._done(machine, slot, user, idempotency_key, "slot.load", {"serial_number": serial})

    async def start(self, machine_id: str, index: int, user: UserEntity, idempotency_key: str | None) -> SlotActionOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return SlotActionOut.model_validate(cached)
        machine, slot = await self._slot(machine_id, index)
        self._require_ready(machine)
        if slot.phase not in FREE_PHASES:
            raise AppError(409, "CONFLICT", f"{machine_id} 的 {index} 号槽正在测试")
        if not slot.serial_number:
            raise AppError(409, "CONFLICT", f"{machine_id} 的 {index} 号槽还没装板")
        upstream = await post_cluster(f"/machines/{machine_id}/slots/{index}/test", None) or {}
        run_id = str(upstream.get("run_id") or f"LOCAL-{machine_id}-{index}-{now_ms()}")
        if await self.session.get(RunOrm, run_id) is None:
            self.session.add(RunOrm(
                run_id=run_id,
                machine_id=machine_id,
                slot_index=index,
                serial_number=slot.serial_number or "",
                plan_id=machine.plan_id or "",
                plan_version=machine.plan_version or 0,
                status="RUNNING",
                passed=None,
                fail_items=[],
                keep_result=True,
                batch_id="",
                ended_at=0,
                result={},
            ))
        slot.phase = "SAMPLING"
        slot.progress = 0
        slot.run_id = run_id
        return await self._done(machine, slot, user, idempotency_key, "slot.start", {})

    async def abort(self, machine_id: str, index: int, user: UserEntity, idempotency_key: str | None) -> SlotActionOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return SlotActionOut.model_validate(cached)
        machine, slot = await self._slot(machine_id, index)
        if slot.phase in FREE_PHASES:
            raise AppError(409, "CONFLICT", f"{machine_id} 的 {index} 号槽没有在测试")
        await post_cluster(f"/machines/{machine_id}/slots/{index}/abort", None)
        if slot.run_id:
            run = await self.session.get(RunOrm, slot.run_id)
            if run is not None and run.status == "RUNNING":
                run.status = "ABORTED"
                run.passed = None
                run.ended_at = now_ms()
        slot.phase = "IDLE"
        slot.progress = 0
        slot.power_w = 0
        slot.run_id = None
        slot.serial_number = None
        return await self._done(machine, slot, user, idempotency_key, "slot.abort", {})

    async def clear_error(self, machine_id: str, index: int, user: UserEntity, idempotency_key: str | None) -> SlotActionOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return SlotActionOut.model_validate(cached)
        machine, slot = await self._slot(machine_id, index)
        await post_cluster(f"/machines/{machine_id}/slots/{index}/clear-error", None)
        if slot.phase == "ERROR":
            slot.phase = "IDLE"
            slot.progress = 0
        slot.last_error = ""
        return await self._done(machine, slot, user, idempotency_key, "slot.clear_error", {})

    async def _slot(self, machine_id: str, index: int) -> tuple[MachineOrm, SlotOrm]:
        machine, slots = await self._require_online(machine_id)
        slot = next((item for item in slots if item.index == index), None)
        if slot is None:
            raise AppError(404, "NOT_FOUND", f"{machine_id} 没有 {index} 号槽")
        return machine, slot

    def _require_ready(self, machine: MachineOrm) -> None:
        if machine.status in {"FAULT", "MAINTENANCE", "OFFLINE"}:
            raise AppError(409, "CONFLICT", f"{machine.machine_id} 当前状态 {machine.status}，不能测试")

    async def _done(self, machine: MachineOrm, slot: SlotOrm, user: UserEntity, key: str | None, action: str, request: dict) -> SlotActionOut:
        machine.last_sync_at = now_ms()
        result = {"phase": slot.phase, "run_id": slot.run_id}
        audit_id = self.audit.record(user.user_id, action, machine.machine_id, {"slot_index": slot.index, **request}, result)
        await self.session.commit()
        body = SlotActionOut(
            audit_id=audit_id,
            machine_id=machine.machine_id,
            slot_index=slot.index,
            phase=slot.phase,
            serial_number=slot.serial_number,
            run_id=slot.run_id,
        )
        await self._publish(machine.machine_id)
        await self._store(key, body)
        return body
