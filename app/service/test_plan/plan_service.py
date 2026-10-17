import json
from collections import defaultdict

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.test_plan import PlanItemOut
from app.models.orm.test_plan import TestPlanOrm
from app.repo.test_plan_repo import TestPlanRepo
from app.service.test_plan.mapping import entity_of, item_out


class PlanService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.plans = TestPlanRepo(session)
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
