import httpx

from app.core.config import settings
from app.core.errors import AppError
from app.service.machines.cluster import post_cluster


def items(body: object, *keys: str) -> list[dict]:
    raw = []
    if isinstance(body, list):
        raw = body
    elif isinstance(body, dict):
        for key in keys:
            if isinstance(body.get(key), list):
                raw = body[key]
                break
    return [item for item in raw if isinstance(item, dict)]


async def get_cluster(path: str) -> dict | list | None:
    """没配集群地址或集群返回 404 时返回 None。"""
    base = settings.cluster_base_url.rstrip("/")
    if not base:
        return None
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    try:
        async with httpx.AsyncClient(timeout=max(settings.cluster_timeout_s, 8)) as client:
            response = await client.get(f"{base}{path}", headers=headers)
    except httpx.TimeoutException as exc:
        raise AppError(504, "CLUSTER_TIMEOUT", "请求集群超时") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "CLUSTER_ERROR", "集群请求失败", {"upstream": str(exc)}) from exc
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise AppError(502, "CLUSTER_ERROR", f"集群返回 {response.status_code}", {"upstream": response.text[:500]})
    if not response.content:
        return {}
    payload = response.json()
    if isinstance(payload, (dict, list)):
        return payload
    return {}


def sim_mode() -> bool:
    return "sim" in settings.cluster_base_url.lower()


async def post_production(path: str, body: dict) -> dict | None:
    return await post_cluster(path, body)
