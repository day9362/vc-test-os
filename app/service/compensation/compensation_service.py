import json

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.errors import AppError
from app.models.dto.compensation import (
    ChannelBiasOut,
    CompChannelOut,
    CompensationIn,
    CompensationOut,
    CompensationWriteOut,
    DriftListOut,
    HistoryItemOut,
    HistoryPageOut,
    SuggestionItemOut,
    SuggestionOut,
)
from app.models.entity.user import UserEntity
from app.repo.audit_repo import AuditRepo
from app.repo.compensation_repo import CompensationRepo
from app.repo.machine_repo import MachineRepo
from app.service.compensation.bias import estimate_channel_bias
from app.service.compensation.cluster import cluster_json


class CompensationService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.machines = MachineRepo(session)
        self.history = CompensationRepo(session)
        self.audit = AuditRepo(session)
        self.redis = redis

    async def channel_bias(self, machine_id: str) -> ChannelBiasOut:
        found = await self.machines.get_with_slots(machine_id)
        if found is None:
            raise AppError(404, "NOT_FOUND", f"机台 {machine_id} 不存在")
        return estimate_channel_bias(machine_id, now_ms())

    async def get_compensation(self, machine_id: str) -> CompensationOut:
        await self._require(machine_id)
        payload = await cluster_json("GET", f"/machines/{machine_id}/compensation")
        return CompensationOut(items=self._items(payload))

    async def put_compensation(self, machine_id: str, body: CompensationIn, user: UserEntity, idempotency_key: str | None) -> CompensationWriteOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return CompensationWriteOut.model_validate(cached)
        if body.mode not in {"add", "set"}:
            raise AppError(422, "VALIDATION_ERROR", "参数校验失败", {"issues": [{"field": "mode", "message": "mode 只能是 add 或 set"}]})
        if not body.compensation:
            raise AppError(422, "VALIDATION_ERROR", "参数校验失败", {"issues": [{"field": "compensation", "message": "compensation 不能为空"}]})
        await self._require(machine_id)
        incoming = [item.model_dump() for item in body.compensation]
        channels = incoming
        if body.mode == "add":
            current = {item.channel: item.value for item in (await self.get_compensation(machine_id)).items}
            for item in incoming:
                current[item["channel"]] = round(current.get(item["channel"], 0) + item["value"], 4)
            channels = [{"channel": channel, "value": value} for channel, value in current.items()]
        payload = {"mode": body.mode, "compensation": incoming}
        upstream = await cluster_json("PUT", f"/machines/{machine_id}/compensation", {"mode": body.mode, "channels": channels})
        items = self._items(upstream) or [CompChannelOut(**row) for row in channels]
        audit_id = self.audit.record(user.user_id, "compensation.write", machine_id, payload, upstream if isinstance(upstream, dict) else {"ok": True})
        self.history.record(user.user_id, machine_id, body.mode, incoming, audit_id)
        out = CompensationWriteOut(audit_id=audit_id, items=items)
        await self.session.commit()
        await self._store(idempotency_key, out)
        return out

    async def suggestion(self, machine_id: str) -> SuggestionOut:
        bias = await self.channel_bias(machine_id)
        items = []
        for item in bias.items:
            if abs(item.value) < bias.threshold_c:
                continue
            items.append(SuggestionItemOut(
                channel=item.channel,
                value=round(-item.value, 3),
                reason=f"标准样品复测偏差 {item.value:+.3f} ℃",
            ))
        return SuggestionOut(items=items, basis_at=bias.measured_at)

    async def list_history(self, machine_id: str, cursor: str | None, limit: int) -> HistoryPageOut:
        await self._require(machine_id)
        if limit < 1 or limit > 500:
            raise AppError(400, "BAD_REQUEST", "limit 需要在 1 到 500 之间")
        if cursor and ":" not in cursor:
            raise AppError(400, "BAD_REQUEST", "cursor 格式不正确")
        rows, next_cursor = await self.history.page(machine_id, cursor, limit)
        return HistoryPageOut(items=[
            HistoryItemOut(
                id=row.id,
                time=row.time,
                actor=row.actor,
                machine_id=row.machine_id,
                mode=row.mode,
                compensation=[CompChannelOut(**item) for item in (row.compensation or []) if isinstance(item, dict)],
                audit_id=row.audit_id,
            )
            for row in rows
        ], next_cursor=next_cursor)

    async def drifts(self, machine_id: str) -> DriftListOut:
        await self._require(machine_id)
        return DriftListOut(items=[], supported=False)

    def _items(self, payload: dict | list) -> list[CompChannelOut]:
        raw = payload if isinstance(payload, list) else payload.get("channels") or payload.get("items") or payload.get("compensation") or []
        return [CompChannelOut(channel=str(row.get("channel") or ""), value=float(row.get("value") or 0)) for row in raw if isinstance(row, dict)]

    async def _cached(self, key: str | None):
        if not key or self.redis is None:
            return None
        raw = await self.redis.get(f"idem:{key}")
        if not raw:
            return None
        return json.loads(raw)

    async def _store(self, key: str | None, body: CompensationWriteOut) -> None:
        if not key or self.redis is None:
            return
        await self.redis.set(f"idem:{key}", json.dumps(body.model_dump()), ex=600)

    async def _require(self, machine_id: str):
        found = await self.machines.get_with_slots(machine_id)
        if found is None:
            raise AppError(404, "NOT_FOUND", f"机台 {machine_id} 不存在")
        return found
