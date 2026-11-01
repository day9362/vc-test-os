import json

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.test_plan import DispatchFailure, DispatchIn, DispatchOut
from app.models.entity.user import UserEntity
from app.repo.audit_repo import AuditRepo
from app.service.machines.cluster import cluster_exchange
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
            if await self._cached(key):
                succeeded.append(machine_id)
                continue
            try:
                await cluster_exchange("PUT", f"/machines/{machine_id}/plan", {"plan_id": body.plan_id, "version": body.version})
            except AppError as exc:
                failed.append(DispatchFailure(machine_id=machine_id, reason=exc.message))
                continue
            succeeded.append(machine_id)
            await self._store(key)
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

    async def _cached(self, key: str | None) -> bool:
        if not key or self.redis is None:
            return False
        try:
            return bool(await self.redis.get(f"idem:{key}"))
        except Exception:
            return False

    async def _store(self, key: str | None) -> None:
        if not key or self.redis is None:
            return
        try:
            await self.redis.set(f"idem:{key}", json.dumps({"ok": True}), ex=600)
        except Exception:
            return
