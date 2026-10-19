import asyncio
import json
import logging
from time import perf_counter

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.settings import (
    ClockIn,
    FaultCatalogItemOut,
    FaultCatalogOut,
    FaultInjectIn,
    JobStatusItemOut,
    JobStatusOut,
    PlatformSettingsOut,
    ScenarioApplyIn,
    ScenarioListOut,
    ScenarioOut,
    SimActionOut,
    TestConnectionIn,
    TestConnectionOut,
)
from app.models.entity.user import UserEntity
from app.repo.audit_repo import AuditRepo
from app.repo.settings_repo import SettingsRepo
from app.service.settings.defaults import JOB_KEYS, min_interval
from app.service.settings.mapping import looks_masked, mask_secret, merge_secrets, settings_entity, settings_out
from app.service.settings.sim import FAULT_CATALOG, SCENARIOS
from app.tasks.job_runs import snapshot
from app.tasks.scheduler import apply_job_intervals

log = logging.getLogger(__name__)


class SettingsService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.settings = SettingsRepo(session)
        self.audit = AuditRepo(session)
        self.redis = redis

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

    async def set_clock(self, body: ClockIn, user: UserEntity, idempotency_key: str | None) -> SimActionOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return SimActionOut.model_validate(cached)
        if body.speed <= 0:
            raise AppError(422, "VALIDATION_ERROR", "设置校验失败", {"issues": [{"field": "speed", "message": "speed 必须大于 0"}]})
        payload = await self._require_sim()
        upstream = await self._proxy("PUT", "/fleet/clock", payload, {"speed": body.speed})
        sim = dict(payload.get("sim") or {})
        sim["speed"] = body.speed
        payload = dict(payload)
        payload["sim"] = sim
        await self.settings.save(payload)
        audit_id = self.audit.record(user.user_id, "sim.clock", "", {"speed": body.speed}, upstream)
        out = SimActionOut(audit_id=audit_id, result=upstream)
        await self.session.commit()
        await self._store(idempotency_key, out)
        return out

    async def apply_scenario(self, name: str, body: ScenarioApplyIn, user: UserEntity, idempotency_key: str | None) -> SimActionOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return SimActionOut.model_validate(cached)
        names = {item["name"] for item in SCENARIOS}
        if name not in names:
            raise AppError(422, "VALIDATION_ERROR", "设置校验失败", {"issues": [{"field": "name", "message": f"未知场景 {name}"}]})
        if not body.machine_id.strip():
            raise AppError(422, "VALIDATION_ERROR", "设置校验失败", {"issues": [{"field": "machine_id", "message": "machine_id 不能为空"}]})
        payload = await self._require_sim()
        upstream = await self._proxy("POST", f"/scenarios/{name}/apply", payload, {"machine_id": body.machine_id})
        audit_id = self.audit.record(user.user_id, "sim.scenario", body.machine_id, {"name": name, "machine_id": body.machine_id}, upstream)
        out = SimActionOut(audit_id=audit_id, result=upstream)
        await self.session.commit()
        await self._store(idempotency_key, out)
        return out

    async def inject_fault(self, body: FaultInjectIn, user: UserEntity, idempotency_key: str | None) -> SimActionOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return SimActionOut.model_validate(cached)
        kinds = {item["kind"] for item in FAULT_CATALOG}
        if body.kind not in kinds:
            raise AppError(422, "VALIDATION_ERROR", "设置校验失败", {"issues": [{"field": "kind", "message": f"未知故障 {body.kind}"}]})
        if not body.machine_id.strip():
            raise AppError(422, "VALIDATION_ERROR", "设置校验失败", {"issues": [{"field": "machine_id", "message": "machine_id 不能为空"}]})
        payload = await self._require_sim()
        data: dict = {"kind": body.kind}
        if body.slot_index is not None:
            data["slot_index"] = body.slot_index
        upstream = await self._proxy("POST", f"/machines/{body.machine_id}/faults", payload, data)
        audit_id = self.audit.record(user.user_id, "sim.fault", body.machine_id, data | {"machine_id": body.machine_id}, upstream)
        out = SimActionOut(audit_id=audit_id, result=upstream)
        await self.session.commit()
        await self._store(idempotency_key, out)
        return out

    async def _require_sim(self) -> dict:
        row = await self.settings.get_or_create()
        payload = row.payload or {}
        if payload.get("source") != "sim":
            raise AppError(409, "CONFLICT", "仅仿真数据源可用")
        return payload

    async def _proxy(self, method: str, path: str, payload: dict, body: dict) -> dict:
        base = ((payload.get("sim") or {}).get("base_url") or "").strip().rstrip("/")
        if not base:
            raise AppError(422, "VALIDATION_ERROR", "设置校验失败", {"issues": [{"field": "sim.base_url", "message": "仿真地址不能为空"}]})
        timeout = max(float((payload.get("cluster") or {}).get("timeout_s") or 5), 30)
        try:
            response = await asyncio.to_thread(_cluster_request, method, f"{base}{path}", timeout, body)
        except httpx.TimeoutException as exc:
            raise AppError(504, "CLUSTER_TIMEOUT", "请求集群超时") from exc
        except httpx.HTTPError as exc:
            raise AppError(502, "CLUSTER_ERROR", "集群请求失败", {"upstream": str(exc)}) from exc
        parsed = _json(response)
        if response.status_code >= 400:
            raise AppError(502, "CLUSTER_ERROR", "集群返回错误", {"upstream": parsed if parsed is not None else response.text[:500]})
        return parsed if isinstance(parsed, dict) else {"ok": True}

    async def _cached(self, key: str | None):
        if not key or self.redis is None:
            return None
        raw = await self.redis.get(f"idem:{key}")
        if not raw:
            return None
        return json.loads(raw)

    async def _store(self, key: str | None, body: SimActionOut) -> None:
        if not key or self.redis is None:
            return
        await self.redis.set(f"idem:{key}", json.dumps(body.model_dump()), ex=600)

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


def _cluster_request(method: str, url: str, timeout: float, body: dict) -> httpx.Response:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        return client.request(method, url, json=body)


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
