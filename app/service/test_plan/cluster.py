import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.config import settings
from app.core.errors import AppError
from app.models.orm.test_plan import TestPlanOrm
from app.repo.test_plan_repo import TestPlanRepo
from app.service.production.cluster import items

log = logging.getLogger(__name__)


async def publish_cluster(payload: dict) -> dict | None:
    base = settings.cluster_base_url.strip().rstrip("/")
    if not base:
        return None
    url = f"{base}/plans" if base.endswith("/api") else f"{base}/api/plans"
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    try:
        async with httpx.AsyncClient(timeout=settings.cluster_timeout_s) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise AppError(504, "CLUSTER_TIMEOUT", "集群发布方案超时") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "CLUSTER_ERROR", "集群发布方案失败") from exc
    if response.status_code >= 400:
        raise AppError(502, "CLUSTER_ERROR", "集群拒绝了方案", {"upstream": response.text[:500]})
    data = response.json()
    return data if isinstance(data, dict) else {}


async def ingest_cluster_plans(session: AsyncSession) -> int:
    """把集群已发布方案写入本地，测试执行下拉和 production precheck 都靠这张表。"""
    repo = TestPlanRepo(session)
    if any(not row.draft for row in await repo.all()):
        return 0
    try:
        payload = await _get_plans()
    except AppError as exc:
        log.warning("ingest plans skipped: %s", exc.message)
        return 0
    added = 0
    for raw in items(payload, "plans", "items"):
        plan_id = str(raw.get("plan_id") or "")
        version = int(raw.get("version") or 0)
        if not plan_id or version <= 0:
            continue
        if await repo.one(plan_id, version):
            continue
        repo.add(TestPlanOrm(
            plan_id=plan_id,
            version=version,
            name=str(raw.get("name") or plan_id),
            start_temp_c=float(raw.get("start_temp_c") or 0),
            duration_s=int(raw.get("duration_s") or 0),
            sample_period_s=float(raw.get("sample_period_s") or 1),
            power_w=float(raw.get("power_w") or 0),
            force_g=float(raw.get("force_g") or 0),
            orientation=int(raw.get("orientation") or 0),
            overtemp_c=float(raw.get("overtemp_c") or 0),
            ambient_low_c=float(raw.get("ambient_low_c") or 0),
            ambient_high_c=float(raw.get("ambient_high_c") or 0),
            limits=list(raw.get("limits") or []),
            author=str(raw.get("author") or "cluster"),
            source="manual",
            draft=False,
            updated_at=now_ms(),
        ))
        added += 1
    return added


async def _get_plans() -> dict | list | None:
    base = settings.cluster_base_url.strip().rstrip("/")
    if not base:
        return None
    url = f"{base}/plans" if base.endswith("/api") else f"{base}/api/plans"
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise AppError(504, "CLUSTER_TIMEOUT", "集群拉取方案超时") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "CLUSTER_ERROR", "集群拉取方案失败") from exc
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise AppError(502, "CLUSTER_ERROR", f"集群返回 {response.status_code}", {"upstream": response.text[:500]})
    if not response.content:
        return {}
    payload = response.json()
    return payload if isinstance(payload, (dict, list)) else {}
