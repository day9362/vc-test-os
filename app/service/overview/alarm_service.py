from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.errors import AppError
from app.models.dto.alarm import AckAllOut, AlarmActionOut, AlarmOut, AlarmPageOut, AttributionOut
from app.models.entity.user import UserEntity
from app.repo.alarm_repo import AlarmRepo
from app.repo.audit_repo import AuditRepo
from app.service.overview.hub import hub
from app.service.overview.mapping import alarm_entity, alarm_out, attribution_out


class AlarmService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.alarms = AlarmRepo(session)
        self.audit = AuditRepo(session)
        self.redis = redis

    async def list_alarms(self, acked: bool | None, machine_id: str | None, level: str | None, cursor: str | None, limit: int) -> AlarmPageOut:
        if limit < 1 or limit > 500:
            raise AppError(400, "BAD_REQUEST", "limit 需要在 1 到 500 之间")
        if level is not None and level not in {"critical", "major", "minor"}:
            raise AppError(400, "BAD_REQUEST", "level 只能是 critical、major 或 minor")
        if cursor and ":" not in cursor:
            raise AppError(400, "BAD_REQUEST", "cursor 格式不正确")
        rows, next_cursor = await self.alarms.page(acked, machine_id, level, cursor, limit)
        return AlarmPageOut(items=[alarm_out(alarm_entity(row)) for row in rows], next_cursor=next_cursor)

    async def acknowledge(self, alarm_id: str, user: UserEntity, idempotency_key: str | None) -> AlarmActionOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return AlarmActionOut.model_validate(cached)
        row = await self._require(alarm_id)
        row.acked = True
        row.acked_by = user.user_id
        row.acked_at = now_ms()
        audit_id = self.audit.record(user.user_id, "alarm.ack", row.machine_id, {"alarm_id": alarm_id}, {"acked": True})
        body = AlarmActionOut(alarm=alarm_out(alarm_entity(row)), audit_id=audit_id)
        await self.session.commit()
        await self._store(idempotency_key, body)
        return body

    async def unacknowledge(self, alarm_id: str, user: UserEntity, idempotency_key: str | None) -> AlarmActionOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return AlarmActionOut.model_validate(cached)
        row = await self._require(alarm_id)
        row.acked = False
        row.acked_by = None
        row.acked_at = None
        audit_id = self.audit.record(user.user_id, "alarm.unack", row.machine_id, {"alarm_id": alarm_id}, {"acked": False})
        body = AlarmActionOut(alarm=alarm_out(alarm_entity(row)), audit_id=audit_id)
        await self.session.commit()
        await self._store(idempotency_key, body)
        return body

    async def acknowledge_all(self, user: UserEntity, idempotency_key: str | None) -> AckAllOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return AckAllOut.model_validate(cached)
        rows = await self.alarms.open_alarms()
        stamp = now_ms()
        for row in rows:
            row.acked = True
            row.acked_by = user.user_id
            row.acked_at = stamp
        audit_id = self.audit.record(user.user_id, "alarm.ack_all", "", {"count": len(rows)}, {"updated": len(rows)})
        body = AckAllOut(updated=len(rows), audit_id=audit_id)
        await self.session.commit()
        for row in rows:
            await hub.publish("alarms", alarm_out(alarm_entity(row)).model_dump())
        await self._store(idempotency_key, body)
        return body

    async def attribution(self, alarm_id: str) -> AttributionOut:
        alarm = await self._require(alarm_id)
        row = await self.alarms.attribution(alarm_id)
        if row is None:
            from app.service.overview.attribution import build_attribution

            row = await build_attribution(self.session, alarm, "系统")
            await self.session.commit()
        return attribution_out(row)

    async def rerun_attribution(self, alarm_id: str, user: UserEntity) -> AttributionOut:
        from app.service.overview.attribution import build_attribution

        alarm = await self._require(alarm_id)
        row = await build_attribution(self.session, alarm, user.name)
        self.audit.record(user.user_id, "alarm.attribution", alarm.machine_id, {"alarm_id": alarm_id}, {"status": row.status})
        await self.session.commit()
        return attribution_out(row)

    async def _require(self, alarm_id: str):
        row = await self.alarms.get(alarm_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", f"告警 {alarm_id} 不存在")
        return row

    async def _cached(self, key: str | None):
        if not key or self.redis is None:
            return None
        raw = await self.redis.get(f"idem:{key}")
        if not raw:
            return None
        import json
        return json.loads(raw)

    async def _store(self, key: str | None, body) -> None:
        if not key or self.redis is None:
            return
        import json
        await self.redis.set(f"idem:{key}", json.dumps(body.model_dump()), ex=600)
