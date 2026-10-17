import httpx

from app.core.config import settings
from app.core.errors import AppError


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
