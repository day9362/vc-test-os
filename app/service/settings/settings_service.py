import asyncio
import logging
from time import perf_counter

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.settings import (
    FaultCatalogItemOut,
    FaultCatalogOut,
    JobStatusItemOut,
    JobStatusOut,
    PlatformSettingsOut,
    ScenarioListOut,
    ScenarioOut,
    TestConnectionIn,
    TestConnectionOut,
)
from app.repo.settings_repo import SettingsRepo
from app.service.settings.defaults import JOB_KEYS, min_interval
from app.service.settings.mapping import looks_masked, mask_secret, merge_secrets, settings_entity, settings_out
from app.service.settings.sim import FAULT_CATALOG, SCENARIOS
from app.tasks.job_runs import snapshot
from app.tasks.scheduler import apply_job_intervals

log = logging.getLogger(__name__)


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

    async def test_connection(self, body: TestConnectionIn) -> TestConnectionOut:
        if body.source not in {"cluster", "sim"}:
            raise AppError(422, "VALIDATION_ERROR", "设置校验失败", {"issues": [{"field": "source", "message": "source 只能是 cluster 或 sim"}]})
        base = body.base_url.strip().rstrip("/")
        if not base:
            raise AppError(422, "VALIDATION_ERROR", "设置校验失败", {"issues": [{"field": "base_url", "message": "base_url 不能为空"}]})
        row = await self.settings.get_or_create()
        payload = row.payload or {}
        token = body.token or ""
        stored_token = ((payload.get("cluster") or {}).get("token") or "") if body.source == "cluster" else ""
        if looks_masked(token) or token == mask_secret(stored_token):
            token = stored_token
        timeout = max(float((payload.get("cluster") or {}).get("timeout_s") or 5), 30)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        started = perf_counter()
        try:
            response = await asyncio.to_thread(_get_fleet, f"{base}/fleet", headers, timeout)
            latency_ms = max(0, round((perf_counter() - started) * 1000))
        except Exception as exc:
            log.warning("test-connection failed: %s", exc)
            return TestConnectionOut(ok=False, latency_ms=max(0, round((perf_counter() - started) * 1000)), machines=0, reachable=0, server_version="")
        if response.status_code >= 400:
            return TestConnectionOut(ok=False, latency_ms=latency_ms, machines=0, reachable=0, server_version=_server_version(response, None))
        payload_json = _json(response)
        machines = _machines(payload_json)
        reachable = sum(1 for item in machines if (item.get("comm_status") or "ONLINE") != "DISCONNECTED")
        return TestConnectionOut(
            ok=True,
            latency_ms=latency_ms,
            machines=len(machines),
            reachable=reachable,
            server_version=_server_version(response, payload_json),
        )

    @staticmethod
    def job_status() -> JobStatusOut:
        seen = snapshot()
        items = []
        for key in JOB_KEYS:
            row = seen.get(key)
            if row is None:
                items.append(JobStatusItemOut(key=key, last_at=None, elapsed_ms=None, failed=None))
            else:
                items.append(JobStatusItemOut(key=key, last_at=row["last_at"], elapsed_ms=row["elapsed_ms"], failed=row["failed"]))
        return JobStatusOut(items=items)

    async def list_scenarios(self) -> ScenarioListOut:
        await self._require_sim()
        return ScenarioListOut(items=[ScenarioOut(**item) for item in SCENARIOS])

    async def list_faults(self) -> FaultCatalogOut:
        await self._require_sim()
        return FaultCatalogOut(items=[FaultCatalogItemOut(**item) for item in FAULT_CATALOG])

    async def _require_sim(self) -> None:
        row = await self.settings.get_or_create()
        if (row.payload or {}).get("source") != "sim":
            raise AppError(409, "CONFLICT", "仅仿真数据源可用")

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


def _get_fleet(url: str, headers: dict[str, str], timeout: float) -> httpx.Response:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        return client.get(url, headers=headers)


def _json(response: httpx.Response) -> dict | list | None:
    try:
        return response.json()
    except Exception:
        return None


def _machines(payload: dict | list | None) -> list[dict]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("machines") or payload.get("items") or []
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _server_version(response: httpx.Response, payload: dict | list | None) -> str:
    for key in ("x-server-version", "x-mockcluster-version", "x-app-version"):
        value = response.headers.get(key)
        if value:
            return value
    if isinstance(payload, dict):
        for key in ("server_version", "version"):
            value = payload.get(key)
            if value:
                return str(value)
    return ""
