import httpx

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
