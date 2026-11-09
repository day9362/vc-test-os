import json

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.test_plan import DispatchFailure, DispatchIn, DispatchOut
from app.models.entity.user import UserEntity
from app.models.orm.machine import MachineOrm
from app.repo.audit_repo import AuditRepo
from app.service.machines.cluster import cluster_exchange
from app.service.machines.hold import hold_machine
from app.service.test_plan.plan_service import PlanService


class DispatchService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.redis = redis
        self.audit = AuditRepo(session)

    async def dispatch(self, body: DispatchIn, user: UserEntity, idempotency_key: str | None) -> DispatchOut:
        if not body.machine_ids:
            raise AppError(422, "VALIDATION_ERROR", "参数校验失败", {"issues": [{"field": "machine_ids", "message": "要列出机台"}]})
        await PlanService(self.session).get_plan(body.plan_id, body.version)
        succeeded: list[str] = []
        failed: list[DispatchFailure] = []
        for machine_id in body.machine_ids:
            key = f"{idempotency_key}:{machine_id}" if idempotency_key else None
            cached = await self._cached(key)
            if cached and cached.get("plan_id") == body.plan_id and cached.get("version") == body.version:
                succeeded.append(machine_id)
                continue
            try:
                await cluster_exchange("PUT", f"/machines/{machine_id}/plan", {"plan_id": body.plan_id, "version": body.version})
            except AppError as exc:
                failed.append(DispatchFailure(machine_id=machine_id, reason=exc.message))
                continue
            machine = await self.session.get(MachineOrm, machine_id)
            if machine is not None:
                machine.plan_id = body.plan_id
                machine.plan_version = body.version
            hold_machine(machine_id)
            succeeded.append(machine_id)
            await self._store(key, body)
        audit_id = self.audit.record(
            user.user_id,
            "plan.dispatch",
            "",
            body.model_dump(),
            {"succeeded": succeeded, "failed": [item.model_dump() for item in failed]},
        )
        await self.session.commit()
        return DispatchOut(
            plan_id=body.plan_id,
            version=body.version,
            succeeded=succeeded,
            failed=failed,
            audit_id=audit_id,
        )

    async def _cached(self, key: str | None) -> dict | None:
        if not key or self.redis is None:
            return None
        try:
            raw = await self.redis.get(f"idem:{key}")
        except Exception:
            return None
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _store(self, key: str | None, body: DispatchIn) -> None:
        if not key or self.redis is None:
            return
        try:
            await self.redis.set(
                f"idem:{key}",
                json.dumps({"ok": True, "plan_id": body.plan_id, "version": body.version}),
                ex=600,
            )
        except Exception:
            return
