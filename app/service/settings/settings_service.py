from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.settings import PlatformSettingsOut
from app.repo.settings_repo import SettingsRepo
from app.service.settings.defaults import JOB_KEYS, min_interval
from app.service.settings.mapping import merge_secrets, settings_entity, settings_out
from app.tasks.scheduler import apply_job_intervals


class SettingsService:
    def __init__(self, session: AsyncSession):
        self.settings = SettingsRepo(session)

    async def get_settings(self) -> PlatformSettingsOut:
        row = await self.settings.get_or_create()
        await self.settings.session.commit()
        return settings_out(settings_entity(row.payload or {}, row.updated_at))

    async def save_settings(self, body: PlatformSettingsOut) -> PlatformSettingsOut:
        incoming = body.model_dump()
        self._validate(incoming)
        row = await self.settings.get_or_create()
        payload = merge_secrets(incoming, row.payload or {})
        row = await self.settings.save(payload)
        await self.settings.session.commit()
        apply_job_intervals(row.payload or {})
        return settings_out(settings_entity(row.payload or {}, row.updated_at))

    def _validate(self, incoming: dict) -> None:
        issues: list[dict] = []
        if incoming.get("source") not in {"cluster", "sim"}:
            issues.append({"field": "source", "message": "source 只能是 cluster 或 sim"})
        on_503 = (incoming.get("cluster") or {}).get("on_503")
        if on_503 not in {"skip", "pause"}:
            issues.append({"field": "cluster.on_503", "message": "on_503 只能是 skip 或 pause"})
        jobs = incoming.get("jobs") or []
        keys = [job.get("key") for job in jobs]
        if set(keys) != set(JOB_KEYS) or len(keys) != len(JOB_KEYS):
            issues.append({"field": "jobs", "message": f"jobs.key 必须恰好是 {', '.join(JOB_KEYS)}"})
        for job in jobs:
            key = job.get("key") or ""
            interval = int(job.get("interval_s") or 0)
            lowest = min_interval(key)
            if key in JOB_KEYS and interval < lowest:
                issues.append({"field": f"jobs.{key}.interval_s", "message": f"{key} 间隔不能低于 {lowest} 秒"})
        if issues:
            raise AppError(422, "VALIDATION_ERROR", "设置校验失败", {"issues": issues})
