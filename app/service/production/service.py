import json

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.errors import AppError
from app.models.dto.production import (
    BatchOut,
    BatchStatOut,
    BatchStatPageOut,
    PrecheckOut,
    ProductModelOut,
    ProductionIn,
    ProductionOut,
    SkippedOut,
    StartOut,
    StopOut,
)
from app.models.entity.user import UserEntity
from app.models.orm.plan import PlanDispatchOrm
from app.models.orm.production import BatchRecordOrm
from app.repo.plan_repo import PlanRepo
from app.repo.production_repo import ProductionRepo
from app.repo.test_plan_repo import TestPlanRepo
from app.repo.audit_repo import AuditRepo
from app.repo.machine_repo import MachineRepo
from app.service.production.cluster import post_production, sim_mode
from app.service.production.mapping import batch_out, model_out, production_out, stat_out
from app.service.production.rules import needs_dispatch, precheck, skip_reasons
from app.service.production.sync import CatalogSync
from app.service.test_plan.cluster import ingest_cluster_plans
from app.service.realtime.publish import push_batch, push_production

STATES = {"running", "done", "stopped"}


class ProductionService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.redis = redis
        self.repo = ProductionRepo(session)
        self.plans = TestPlanRepo(session)
        self.machines = MachineRepo(session)
        self.history = PlanRepo(session)
        self.audit = AuditRepo(session)
        self.sync = CatalogSync(session)

    async def models(self) -> list[ProductModelOut]:
        await self._prepare()
        return [model_out(row) for row in await self.repo.models()]

    async def batches(self) -> list[BatchOut]:
        await self._prepare()
        return [batch_out(row) for row in await self.repo.batches()]

    async def batch_stats(self, state: str | None, model: str | None, q: str | None, cursor: str | None, limit: int) -> BatchStatPageOut:
        self._limit(limit)
        self._state(state)
        self._cursor(cursor)
        await self._prepare()
        rows, next_cursor = await self.repo.page_stats(state=state, model=model, q=q, cursor=cursor, limit=limit)
        return BatchStatPageOut(items=[stat_out(row) for row in rows], next_cursor=next_cursor)

    async def batch_stat(self, batch_id: str) -> BatchStatOut:
        await self._prepare()
        row = await self.repo.batch(batch_id)
        if row is None or row.state not in STATES:
            raise AppError(404, "NOT_FOUND", "批次不存在")
        return stat_out(row)

    async def production(self) -> ProductionOut | None:
        await self._prepare()
        row = await self.repo.production()
        if row is None:
            return None
        return production_out(row)

    async def precheck_body(self, body: ProductionIn) -> PrecheckOut:
        await self._prepare()
        issues = await self._issues(body)
        return PrecheckOut(ok=not any(item.level == "danger" for item in issues), issues=issues)

    async def start(self, body: ProductionIn, user: UserEntity, key: str | None) -> StartOut:
        cached = await self._cached(key)
        if cached:
            return StartOut.model_validate(cached)
        await self._prepare()
        context = await self._context(body)
        plan_name = context.pop("plan_name")
        issues = precheck(body, sim_mode=sim_mode(), **context)
        if any(item.level == "danger" for item in issues):
            raise AppError(422, "VALIDATION_ERROR", "下发前校验未通过", {"issues": [item.model_dump() for item in issues]})
        current = await self.repo.production()
        if current is not None:
            raise AppError(409, "CONFLICT", "已有连续生产在进行")
        upstream = await post_production("/fleet/production/start", body.model_dump())
        accepted, skipped = _outcome(upstream, body.machine_ids, skip_reasons(body, context["machines"]))
        batch_id = _batch_id(upstream, body)
        if not batch_id:
            raise AppError(502, "CLUSTER_ERROR", "集群没有返回 batch_id")
        queue = _queue(upstream, context["remaining"], body)
        production = await self.repo.production_row()
        production.active = True
        production.batch_id = batch_id
        production.queue_remaining = queue
        production.plan_id = body.plan_id
        production.plan_version = body.plan_version
        row = await self._touch_batch(batch_id, body, accepted, queue)
        await self._dispatch(accepted, context["machines"], body, plan_name)
        audit_id = self.audit.record(
            user.user_id, "production.start", "",
            body.model_dump(),
            {"batch_id": batch_id, "accepted": accepted, "skipped": [item.model_dump() for item in skipped]},
        )
        await self.session.commit()
        result = StartOut(batch_id=batch_id, accepted=accepted, skipped=skipped, audit_id=audit_id)
        await self._store(key, result)
        await push_production(production_out(production).model_dump())
        await push_batch(stat_out(row).model_dump())
        return result

    async def stop(self, batch_id: str, user: UserEntity, key: str | None) -> StopOut:
        cached = await self._cached(key)
        if cached:
            return StopOut.model_validate(cached)
        row = await self.repo.batch(batch_id)
        current = await self.repo.production()
        running = (row is not None and row.state == "running") or (current is not None and current.batch_id == batch_id)
        if row is None and not running:
            raise AppError(404, "NOT_FOUND", "批次不存在")
        if not running:
            raise AppError(409, "CONFLICT", "该批次不在连续生产中")
        await post_production("/fleet/production/stop", {"batch_id": batch_id})
        if current is not None and current.batch_id == batch_id:
            current.active = False
        if row is not None:
            row.state = "stopped"
            row.ended_at = now_ms()
            row.eta_s = None
        audit_id = self.audit.record(user.user_id, "production.stop", "", {"batch_id": batch_id}, {"ok": True})
        await self.session.commit()
        result = StopOut(audit_id=audit_id)
        await self._store(key, result)
        await push_production(None)
        if row is not None:
            await push_batch(stat_out(row).model_dump())
        return result

    async def _prepare(self) -> None:
        if not await self.repo.models() or not await self.repo.batches():
            await self.sync.pull()
        await ingest_cluster_plans(self.session)
        await self.sync.refresh_stats()
        await self.session.commit()

    async def _issues(self, body: ProductionIn):
        context = await self._context(body)
        context.pop("plan_name", None)
        return precheck(body, sim_mode=sim_mode(), **context)

    async def _context(self, body: ProductionIn) -> dict:
        plan = await self.plans.one(body.plan_id, body.plan_version)
        plan_found = plan is not None and not plan.draft
        batch_known = False
        remaining = None
        model_power = None
        if body.batch_id:
            batch = await self.repo.batch(body.batch_id)
            batch_known = batch is not None
            if batch is not None:
                remaining = batch.remaining
                model = await self.repo.model(batch.model)
                if model is not None:
                    model_power = model.power_w
        machines = []
        for machine, slots in await self.machines.list_with_slots():
            machines.append({
                "machine_id": machine.machine_id,
                "status": machine.status,
                "comm_status": machine.comm_status,
                "plan_id": machine.plan_id,
                "plan_version": machine.plan_version,
                "speed": machine.speed,
                "slots": [{"phase": slot.phase} for slot in slots],
            })
        return {
            "plan_found": plan_found,
            "plan_power": plan.power_w if plan_found else None,
            "plan_name": plan.name if plan_found else body.plan_id,
            "limits": list(plan.limits or []) if plan_found else [],
            "model_power": model_power,
            "remaining": remaining,
            "batch_known": batch_known,
            "machines": machines,
        }

    async def _touch_batch(self, batch_id: str, body: ProductionIn, machine_ids: list[str], queue: int) -> BatchRecordOrm:
        row = await self.repo.batch(batch_id)
        if row is None:
            row = BatchRecordOrm(batch_id=batch_id, model="", count=queue, remaining=queue, state="running")
            self.session.add(row)
        row.state = "running"
        row.ended_at = None
        row.plan_id = body.plan_id
        row.plan_version = body.plan_version
        row.machine_ids = list(machine_ids)
        if not row.started_at:
            row.started_at = now_ms()
        if queue:
            row.remaining = queue
        await self.session.flush()
        return row

    async def _dispatch(self, accepted: list[str], machines: list[dict], body: ProductionIn, plan_name: str) -> None:
        known = {row["machine_id"]: row for row in machines}
        stamp = now_ms()
        for machine_id in accepted:
            snapshot = known.get(machine_id)
            if snapshot is None or not needs_dispatch(snapshot, body.plan_id, body.plan_version):
                continue
            for previous in await self.history.history(machine_id):
                if previous.ended_at is None:
                    previous.ended_at = stamp
            self.session.add(PlanDispatchOrm(
                machine_id=machine_id,
                plan_id=body.plan_id,
                name=plan_name,
                version=body.plan_version,
                started_at=stamp,
                ended_at=None,
            ))
            found = await self.machines.get_with_slots(machine_id)
            if found is None:
                continue
            machine, _slots = found
            machine.plan_id = body.plan_id
            machine.plan_version = body.plan_version
            if machine.status in {"CREATED", "OFFLINE", "STOPPED"}:
                machine.status = "READY"
            machine.last_sync_at = stamp

    def _limit(self, limit: int) -> None:
        if limit < 1 or limit > 500:
            raise AppError(400, "BAD_REQUEST", "limit 需要在 1 到 500 之间")

    def _state(self, state: str | None) -> None:
        if state and state not in STATES:
            raise AppError(400, "BAD_REQUEST", "state 只能是 running、done 或 stopped")

    def _cursor(self, cursor: str | None) -> None:
        if not cursor:
            return
        mark, _, batch_id = cursor.partition("|")
        if not mark.isdigit() or not batch_id:
            raise AppError(400, "BAD_REQUEST", "cursor 格式不正确")

    async def _cached(self, key: str | None):
        if not key or self.redis is None:
            return None
        raw = await self.redis.get(f"idem:prod:{key}")
        return json.loads(raw) if raw else None

    async def _store(self, key: str | None, body: StartOut | StopOut) -> None:
        if not key or self.redis is None:
            return
        await self.redis.set(f"idem:prod:{key}", body.model_dump_json(), ex=600)


def _batch_id(upstream: dict | None, body: ProductionIn) -> str:
    if isinstance(upstream, dict) and upstream.get("batch_id"):
        return str(upstream["batch_id"])
    if body.batch_id:
        return body.batch_id
    if upstream is None and body.serial_numbers:
        return body.serial_numbers[0]
    return ""


def _queue(upstream: dict | None, remaining: int | None, body: ProductionIn) -> int:
    if isinstance(upstream, dict) and upstream.get("queue_remaining") is not None:
        return int(upstream["queue_remaining"])
    if remaining is not None:
        return int(remaining)
    if body.max_count:
        return int(body.max_count)
    return len(body.serial_numbers or [])


def _outcome(data: dict | None, requested: list[str], local_skips: list[tuple[str, str]]) -> tuple[list[str], list[SkippedOut]]:
    reasons = dict(local_skips)
    if not isinstance(data, dict):
        skipped = [SkippedOut(machine_id=machine_id, reason=reason) for machine_id, reason in local_skips]
        accepted = [machine_id for machine_id in requested if machine_id not in reasons]
        return accepted, skipped
    skipped = []
    for item in data.get("skipped") or []:
        if isinstance(item, dict) and item.get("machine_id"):
            skipped.append(SkippedOut(machine_id=str(item["machine_id"]), reason=str(item.get("reason") or "被跳过")))
    accepted_raw = data.get("accepted")
    if isinstance(accepted_raw, list):
        accepted = [str(item) for item in accepted_raw]
    else:
        accepted = []
    if not skipped:
        skipped_ids = set(requested) - set(accepted)
        if accepted_raw is None:
            skipped_ids = set(reasons)
        skipped = [SkippedOut(machine_id=machine_id, reason=reasons.get(machine_id, "被跳过")) for machine_id in requested if machine_id in skipped_ids]
    if not isinstance(accepted_raw, list):
        skipped_ids = {item.machine_id for item in skipped}
        accepted = [machine_id for machine_id in requested if machine_id not in skipped_ids]
    return accepted, skipped
