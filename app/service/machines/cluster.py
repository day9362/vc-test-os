import httpx

from app.core.errors import AppError
from app.service.settings.cluster_policy import async_send, cluster_base_url, cluster_headers, note_cluster_unavailable, request_timeout


async def post_cluster(path: str, body: dict | None) -> dict:
    """没有配置集群地址时直接失败，不把本地状态当成已经执行。"""
    base = cluster_base_url()
    if not base:
        raise AppError(409, "CONFLICT", "没有配置集群地址")
    headers = cluster_headers()
    try:
        response = await async_send("POST", f"{base}{path}", timeout=request_timeout(), headers=headers, json_body=body)
    except httpx.TimeoutException as exc:
        raise AppError(504, "CLUSTER_TIMEOUT", "请求集群超时") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "CLUSTER_ERROR", "集群请求失败", {"upstream": str(exc)}) from exc
    if response.status_code == 503:
        note_cluster_unavailable()
        raise AppError(503, "MACHINE_DISCONNECTED", "集群返回 503", {"upstream": _body(response)})
    if response.status_code >= 400:
        raise AppError(502, "CLUSTER_ERROR", f"集群返回 {response.status_code}", {"upstream": _body(response)})
    if not response.content:
        return {}
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


async def cluster_exchange(method: str, path: str, body: dict | None = None) -> dict | list:
    """把集群的 404、409、503 原样变成平台错误，供下发方案、查板和放回待测使用。"""
    base = cluster_base_url()
    if not base:
        raise AppError(409, "CONFLICT", "没有配置集群地址")
    headers = cluster_headers()
    try:
        response = await async_send(method, f"{base}{path}", timeout=request_timeout(), headers=headers, json_body=body)
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
        note_cluster_unavailable()
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
