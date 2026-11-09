import httpx

from app.core.errors import AppError
from app.service.settings.cluster_policy import async_send, cluster_base_url, cluster_headers, note_cluster_unavailable, request_timeout


async def cluster_json(method: str, path: str, body: dict | None = None) -> dict | list:
    base = cluster_base_url()
    if not base:
        raise AppError(409, "CONFLICT", "没有配置集群地址")
    try:
        response = await async_send(method, f"{base}{path}", timeout=request_timeout(), headers=cluster_headers(), json_body=body)
    except httpx.TimeoutException as exc:
        raise AppError(504, "CLUSTER_TIMEOUT", "请求集群超时") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "CLUSTER_ERROR", "集群请求失败", {"upstream": str(exc)}) from exc
    try:
        parsed = response.json()
    except Exception:
        parsed = None
    if response.status_code == 503:
        note_cluster_unavailable()
    if response.status_code >= 400:
        raise AppError(502, "CLUSTER_ERROR", "集群返回错误", {"upstream": parsed if parsed is not None else response.text[:500]})
    if isinstance(parsed, (dict, list)):
        return parsed
    return {}
