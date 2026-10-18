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
        async with httpx.AsyncClient(timeout=settings.cluster_timeout_s) as client:
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


def _body(response: httpx.Response):
    try:
        return response.json()
    except Exception:
        return {"text": response.text[:500]}
