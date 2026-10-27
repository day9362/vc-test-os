import json
from collections import defaultdict
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.config import settings
from app.core.errors import AppError
from app.models.dto.test_plan import DeleteOut, DraftOut, FromTextOut, PlanBody, PlanItemOut, PublishIn, PublishOut, ValidateOut
from app.models.entity.user import UserEntity
from app.models.orm.alarm import AiCallOrm
from app.models.orm.machine import MachineOrm
from app.models.orm.test_plan import TestPlanOrm
from app.repo.audit_repo import AuditRepo
from app.repo.test_plan_repo import TestPlanRepo
from app.service.agent.draft import generate_draft
from app.service.test_plan.cluster import ingest_cluster_plans, publish_cluster
from app.service.test_plan.mapping import entity_of, item_out
from app.service.test_plan.validate import fleet_bounds, validate_plan


class PlanService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.plans = TestPlanRepo(session)
        self.audit = AuditRepo(session)
        self.redis = redis

    async def list_plans(self) -> list[PlanItemOut]:
        if await ingest_cluster_plans(self.session):
            await self.session.commit()
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

    async def create_draft(self, body: PlanBody, user: UserEntity, idempotency_key: str | None, source: str = "manual") -> DraftOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return DraftOut.model_validate(cached)
        if not body.name.strip():
            raise AppError(400, "BAD_REQUEST", "方案名称不能为空")
        plan_id = f"DRAFT-{uuid4().hex[:8]}"
        row = self._row(plan_id, 0, body, user.name, source, True)
        self.plans.add(row)
        audit_id = self.audit.record(user.user_id, "plan.draft", "", {"plan_id": plan_id, "name": body.name}, {"draft": True})
        await self.session.commit()
        result = DraftOut(**item_out(entity_of(row, [])).model_dump(), audit_id=audit_id)
        await self._store(idempotency_key, result)
        return result

    async def update_draft(self, plan_id: str, body: PlanBody, user: UserEntity, idempotency_key: str | None) -> DraftOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return DraftOut.model_validate(cached)
        row = await self._draft(plan_id)
        if not body.name.strip():
            raise AppError(400, "BAD_REQUEST", "方案名称不能为空")
        fresh = self._row(plan_id, 0, body, row.author, row.source, True)
        for field in ("name", "start_temp_c", "duration_s", "sample_period_s", "power_w", "force_g", "orientation", "overtemp_c", "ambient_low_c", "ambient_high_c", "limits", "updated_at"):
            setattr(row, field, getattr(fresh, field))
        audit_id = self.audit.record(user.user_id, "plan.draft_update", "", {"plan_id": plan_id}, {"name": body.name})
        await self.session.commit()
        result = DraftOut(**item_out(entity_of(row, [])).model_dump(), audit_id=audit_id)
        await self._store(idempotency_key, result)
        return result

    async def delete_draft(self, plan_id: str, user: UserEntity, idempotency_key: str | None) -> DeleteOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return DeleteOut.model_validate(cached)
        row = await self._draft(plan_id)
        await self.plans.delete(row)
        audit_id = self.audit.record(user.user_id, "plan.draft_delete", "", {"plan_id": plan_id}, {"deleted": True})
        result = DeleteOut(audit_id=audit_id)
        await self.session.commit()
        await self._store(idempotency_key, result)
        return result

    async def draft_from_text(self, text: str, user: UserEntity, idempotency_key: str | None) -> FromTextOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return FromTextOut.model_validate(cached)
        if not text.strip():
            raise AppError(400, "BAD_REQUEST", "描述不能为空")
        started = now_ms()
        body, notes, usage = await generate_draft(text)
        created = await self.create_draft(body, user, None, source="agent")
        self.session.add(AiCallOrm(
            id=f"call-{uuid4().hex[:8]}",
            time=now_ms(),
            module="agent.plan",
            user=user.name,
            model=settings.anthropic_model or "agent",
            input_tokens=usage.input,
            output_tokens=usage.output,
            latency_ms=max(now_ms() - started, 1),
            ok=True,
            ref={"plan_id": created.plan.plan_id},
        ))
        audit_id = self.audit.record(user.user_id, "plan.from_text", "", {"text": text[:80]}, {"plan_id": created.plan.plan_id})
        result = FromTextOut(plan=created.plan, meta=created.meta, notes=notes, usage=usage, audit_id=audit_id)
        await self.session.commit()
        await self._store(idempotency_key, result)
        return result

    async def _draft(self, plan_id: str) -> TestPlanOrm:
        row = await self.plans.one(plan_id, 0)
        if row is None or not row.draft:
            if row is None and not await self.plans.of(plan_id):
                raise AppError(404, "NOT_FOUND", f"草稿 {plan_id} 不存在")
            raise AppError(409, "CONFLICT", "已发布方案不能直接修改")
        return row

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
