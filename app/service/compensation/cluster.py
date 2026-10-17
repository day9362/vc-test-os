import asyncio

import httpx

from app.core.config import settings
from app.core.errors import AppError

DEFAULT_BASE = "https://cluster.simuoss.cn/api"


def cluster_base() -> str:
    return (settings.cluster_base_url or DEFAULT_BASE).rstrip("/")


def _request(method: str, url: str, timeout: float, body: dict | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        return client.request(method, url, headers=headers, json=body)


async def cluster_json(method: str, path: str, body: dict | None = None) -> dict | list:
    try:
        response = await asyncio.to_thread(_request, method, f"{cluster_base()}{path}", max(settings.cluster_timeout_s, 30), body)
    except httpx.TimeoutException as exc:
        raise AppError(504, "CLUSTER_TIMEOUT", "请求集群超时") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "CLUSTER_ERROR", "集群请求失败", {"upstream": str(exc)}) from exc
    try:
        parsed = response.json()
    except Exception:
        parsed = None
    if response.status_code >= 400:
        raise AppError(502, "CLUSTER_ERROR", "集群返回错误", {"upstream": parsed if parsed is not None else response.text[:500]})
    if isinstance(parsed, (dict, list)):
        return parsed
    return {}
