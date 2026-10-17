import json
from collections import defaultdict
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.errors import AppError
from app.models.dto.test_plan import PlanBody, PlanItemOut, PublishIn, PublishOut, ValidateOut
from app.models.entity.user import UserEntity
from app.models.orm.machine import MachineOrm
from app.models.orm.test_plan import TestPlanOrm
from app.repo.audit_repo import AuditRepo
from app.repo.test_plan_repo import TestPlanRepo
from app.service.test_plan.cluster import publish_cluster
from app.service.test_plan.mapping import entity_of, item_out
from app.service.test_plan.validate import fleet_bounds, validate_plan


class PlanService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.plans = TestPlanRepo(session)
        self.audit = AuditRepo(session)
        self.redis = redis

    async def list_plans(self) -> list[PlanItemOut]:
        grouped: dict[str, list[TestPlanOrm]] = defaultdict(list)
        for row in await self.plans.all():
            grouped[row.plan_id].append(row)
        items = [item_out(entity_of(current, versions)) for current, versions in (self._current(rows) for rows in grouped.values())]
        items.sort(key=lambda item: (not item.meta.draft, -item.meta.updated_at))
        return items

    async def get_plan(self, plan_id: str, version: int | None) -> PlanItemOut:
        rows = await self._require_group(plan_id)
        current, versions = self._current(rows)
        if version is None:
            return item_out(entity_of(current, versions))
        row = next((item for item in rows if item.version == version and not item.draft), None)
        if row is None:
            raise AppError(404, "NOT_FOUND", f"方案 {plan_id} 没有 v{version}")
        return item_out(entity_of(row, versions))

    async def validate(self, body: PlanBody) -> ValidateOut:
        capabilities = list((await self.session.execute(select(MachineOrm.capability))).scalars().all())
        return validate_plan(body, fleet_bounds([item for item in capabilities if isinstance(item, dict)]))

    async def publish(self, body: PublishIn, user: UserEntity, idempotency_key: str | None) -> PublishOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return PublishOut.model_validate(cached)
        checked = await self.validate(body)
        if not checked.ok:
            raise AppError(422, "VALIDATION_ERROR", "方案未通过校验", {"issues": [issue.model_dump() for issue in checked.issues]})
        cluster = await publish_cluster(body.model_dump())
        rows = await self.plans.of(body.plan_id) if body.plan_id else []
        published = [row for row in rows if not row.draft]
        draft = next((row for row in rows if row.draft), None)
        if published:
            plan_id = body.plan_id or published[0].plan_id
            version = int(cluster.get("version")) if cluster and cluster.get("version") is not None else max(row.version for row in published) + 1
        else:
            plan_id = str(cluster.get("plan_id")) if cluster and cluster.get("plan_id") else f"PLAN-{uuid4().hex[:8]}"
            version = int(cluster.get("version")) if cluster and cluster.get("version") is not None else 1
            if draft is not None:
                await self.plans.delete(draft)
        if await self.plans.one(plan_id, version):
            raise AppError(409, "CONFLICT", f"方案 {plan_id} 已有 v{version}")
        self.plans.add(self._row(plan_id, version, body, user.name, "manual", False))
        audit_id = self.audit.record(user.user_id, "plan.publish", "", {"plan_id": plan_id, "name": body.name}, {"version": version})
        result = PublishOut(plan_id=plan_id, version=version, audit_id=audit_id)
        await self.session.commit()
        await self._store(idempotency_key, result)
        return result

    def _row(self, plan_id: str, version: int, body: PlanBody, author: str, source: str, draft: bool) -> TestPlanOrm:
        return TestPlanOrm(
            plan_id=plan_id,
            version=version,
            name=body.name.strip(),
            start_temp_c=body.start_temp_c,
            duration_s=body.duration_s,
            sample_period_s=body.sample_period_s,
            power_w=body.power_w,
            force_g=body.force_g,
            orientation=body.orientation,
            overtemp_c=body.overtemp_c,
            ambient_low_c=body.ambient_low_c,
            ambient_high_c=body.ambient_high_c,
            limits=[limit.model_dump() for limit in body.limits],
            author=author,
            source=source,
            draft=draft,
            updated_at=now_ms(),
        )

    def _current(self, rows: list[TestPlanOrm]) -> tuple[TestPlanOrm, list[int]]:
        published = [row for row in rows if not row.draft]
        if published:
            current = max(published, key=lambda row: row.version)
            return current, sorted(row.version for row in published)
        return rows[0], []

    async def _require_group(self, plan_id: str) -> list[TestPlanOrm]:
        rows = await self.plans.of(plan_id)
        if not rows:
            raise AppError(404, "NOT_FOUND", f"方案 {plan_id} 不存在")
        return rows

    async def _cached(self, key: str | None):
        if not key or self.redis is None:
            return None
        raw = await self.redis.get(f"idem:{key}")
        if not raw:
            return None
        return json.loads(raw)

    async def _store(self, key: str | None, body) -> None:
        if not key or self.redis is None:
            return
        await self.redis.set(f"idem:{key}", json.dumps(body.model_dump()), ex=600)
