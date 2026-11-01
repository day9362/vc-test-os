import httpx

from app.core.config import settings
from app.core.errors import AppError


async def post_cluster(path: str, body: dict | None) -> dict | None:
    """没有配置集群地址时返回 None，由本地状态直接生效。"""
    base = settings.cluster_base_url.rstrip("/")
    if not base:
        return None
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    try:
        async with httpx.AsyncClient(timeout=max(settings.cluster_timeout_s, 20)) as client:
            response = await client.post(f"{base}{path}", headers=headers, json=body)
    except httpx.TimeoutException as exc:
        raise AppError(504, "CLUSTER_TIMEOUT", "请求集群超时") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "CLUSTER_ERROR", "集群请求失败", {"upstream": str(exc)}) from exc
    if response.status_code == 503:
        raise AppError(503, "MACHINE_DISCONNECTED", "集群返回 503", {"upstream": _body(response)})
    if response.status_code >= 400:
        raise AppError(502, "CLUSTER_ERROR", f"集群返回 {response.status_code}", {"upstream": _body(response)})
    if not response.content:
        return {}
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


async def cluster_exchange(method: str, path: str, body: dict | None = None) -> dict | list:
    """把集群的 404、409、503 原样变成平台错误，供下发方案、查板和放回待测使用。"""
    base = settings.cluster_base_url.rstrip("/")
    if not base:
        raise AppError(409, "CONFLICT", "没有配置集群地址")
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    try:
        async with httpx.AsyncClient(timeout=max(settings.cluster_timeout_s, 20), trust_env=False) as client:
            response = await client.request(method, f"{base}{path}", headers=headers, json=body)
    except httpx.TimeoutException as exc:
        raise AppError(504, "CLUSTER_TIMEOUT", "请求集群超时") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "CLUSTER_ERROR", "集群请求失败", {"upstream": str(exc)}) from exc
    upstream = _body(response)
    if response.status_code == 404:
        raise AppError(404, "NOT_FOUND", "集群没有这项资料", {"upstream": upstream})
    if response.status_code == 409:
        message = upstream.get("message") if isinstance(upstream, dict) else None
        raise AppError(409, "CONFLICT", str(message or "集群拒绝了这次操作"), {"upstream": upstream})
    if response.status_code == 503:
        raise AppError(503, "MACHINE_DISCONNECTED", "机台通信已断开", {"upstream": upstream})
    if response.status_code >= 400:
        raise AppError(502, "CLUSTER_ERROR", f"集群返回 {response.status_code}", {"upstream": upstream})
    if not response.content:
        return {}
    payload = response.json()
    if isinstance(payload, (dict, list)):
        return payload
    return {}


def _body(response: httpx.Response):
    try:
        return response.json()
    except Exception:
        return {"text": response.text[:500]}
