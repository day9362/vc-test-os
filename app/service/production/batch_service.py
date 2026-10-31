import json

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.production import BatchCreateIn, BatchCreateOut
from app.models.entity.user import UserEntity
from app.models.orm.production import BatchRecordOrm
from app.repo.audit_repo import AuditRepo
from app.repo.production_repo import ProductionRepo
from app.service.production.cluster import post_production
from app.service.production.mapping import batch_out


class BatchCommandService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.redis = redis
        self.repo = ProductionRepo(session)
        self.audit = AuditRepo(session)

    async def create(self, body: BatchCreateIn, user: UserEntity, idempotency_key: str | None) -> BatchCreateOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return BatchCreateOut.model_validate(cached)
        model = body.model.strip()
        known = {row.model for row in await self.repo.models()}
        if known and model not in known:
            raise AppError(422, "VALIDATION_ERROR", "参数校验失败", {"issues": [{"field": "model", "message": f"没有型号 {model}"}]})
        request = {"model": model, "count": body.count, "defect_ratio": body.defect_ratio, "batch_factor": body.batch_factor}
        upstream = await post_production("/products/batches", request)
        if upstream is None:
            raise AppError(409, "CONFLICT", "没有配置集群地址，不能生成批次")
        raw = upstream.get("batch") if isinstance(upstream.get("batch"), dict) else {}
        batch_id = str(raw.get("batch_id") or "")
        if not batch_id:
            raise AppError(502, "CLUSTER_ERROR", "集群没有返回批次号", {"upstream": upstream})
        serials = [str(item) for item in upstream.get("serial_numbers") or []]
        row = await self.repo.batch(batch_id) or BatchRecordOrm(batch_id=batch_id, state="")
        row.model = str(raw.get("model") or model)
        row.count = int(raw.get("count") or body.count)
        row.defect_ratio = float(raw.get("defect_ratio") if raw.get("defect_ratio") is not None else body.defect_ratio)
        row.batch_factor = float(raw.get("batch_factor") or body.batch_factor)
        row.remaining = len(serials) or row.count
        await self.repo.save_batch(row)
        audit_id = self.audit.record(user.user_id, "batch.create", "", request, {"batch_id": batch_id, "count": len(serials)})
        await self.session.commit()
        out = BatchCreateOut(audit_id=audit_id, batch=batch_out(row), serial_numbers=serials)
        await self._store(idempotency_key, out)
        return out

    async def _cached(self, key: str | None):
        if not key or self.redis is None:
            return None
        raw = await self.redis.get(f"idem:{key}")
        return json.loads(raw) if raw else None

    async def _store(self, key: str | None, body: BatchCreateOut) -> None:
        if not key or self.redis is None:
            return
        await self.redis.set(f"idem:{key}", body.model_dump_json(), ex=600)
