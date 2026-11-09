import httpx

from app.core.config import settings

TIMEOUT_MIN = 1
TIMEOUT_MAX = 8
SLOT_TIMEOUT_MAX = 4
RETRIES_MAX = 5

_timeout = float(TIMEOUT_MAX)
_retries = 2


def clamp_timeout(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(TIMEOUT_MAX)
    if number < TIMEOUT_MIN:
        return float(TIMEOUT_MIN)
    if number > TIMEOUT_MAX:
        return float(TIMEOUT_MAX)
    return number


def clamp_retries(value: object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    if isinstance(value, bool):
        return 0
    return min(max(number, 0), RETRIES_MAX)


def apply_cluster_policy(payload: dict) -> None:
    global _timeout, _retries
    cluster = payload.get("cluster") or {}
    _timeout = clamp_timeout(cluster.get("timeout_s"))
    _retries = clamp_retries(cluster.get("retries"))


def request_timeout(*, slot: bool = False) -> float:
    if slot:
        return min(_timeout, float(SLOT_TIMEOUT_MAX))
    return _timeout


def retry_count() -> int:
    return _retries


_base = ""
_token = ""
_source = ""
_on_503 = "skip"
_applied = False
_paused = False


def apply_endpoint(payload: dict) -> None:
    """同步、机台指令和补偿改走这里。保存设置或进程启动时刷新，并解除同步暂停。"""
    global _base, _token, _source, _on_503, _applied, _paused
    source = str(payload.get("source") or "cluster")
    if source == "sim":
        sim = payload.get("sim") or {}
        _base = str(sim.get("base_url") or "").strip().rstrip("/")
        _token = ""
    else:
        cluster = payload.get("cluster") or {}
        _base = str(cluster.get("base_url") or "").strip().rstrip("/")
        token = str(cluster.get("token") or "")
        _token = "" if "****" in token else token
    _source = source
    _on_503 = str((payload.get("cluster") or {}).get("on_503") or "skip")
    _applied = True
    _paused = False


def cluster_base_url() -> str:
    if _applied:
        return _base
    return settings.cluster_base_url.strip().rstrip("/")


def cluster_token() -> str:
    if _applied:
        return _token
    return settings.cluster_token


def cluster_headers() -> dict[str, str]:
    token = cluster_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def using_sim() -> bool:
    if _applied:
        return _source == "sim"
    return "sim" in settings.cluster_base_url.lower()


def on_503_mode() -> str:
    return _on_503 if _applied else "skip"


def note_cluster_unavailable() -> None:
    global _paused
    if on_503_mode() == "pause":
        _paused = True


def sync_paused() -> bool:
    return _paused and on_503_mode() == "pause"


def _again(attempt: int) -> bool:
    return attempt < retry_count()


async def async_send(method: str, url: str, *, timeout: float, headers: dict | None = None, json_body: dict | None = None) -> httpx.Response:
    """超时、连接失败和 5xx 按设置的次数重试。4xx 不重试。"""
    last: Exception | None = None
    response: httpx.Response | None = None
    for attempt in range(retry_count() + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=True) as client:
                response = await client.request(method, url, headers=headers, json=json_body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
            if _again(attempt):
                continue
            raise
        if response.status_code >= 500 and _again(attempt):
            continue
        return response
    raise last or RuntimeError("cluster request failed")


def sync_send(method: str, url: str, *, timeout: float, headers: dict | None = None, json_body: dict | None = None) -> httpx.Response:
    last: Exception | None = None
    response: httpx.Response | None = None
    for attempt in range(retry_count() + 1):
        try:
            with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=True) as client:
                response = client.request(method, url, headers=headers, json=json_body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
            if _again(attempt):
                continue
            raise
        if response.status_code >= 500 and _again(attempt):
            continue
        return response
    raise last or RuntimeError("cluster request failed")
