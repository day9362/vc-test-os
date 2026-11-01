import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.identity import Identity


@dataclass
class Reply:
    ok: bool
    status: int
    body: Any
    code: str = ""
    message: str = ""
    detail: Any = None


class Backend:
    """调用 VC-TestOS 后端 /api/v1。只读模式用服务账号，用户模式原样转发用户令牌。"""

    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(
            base_url=(base_url or settings.vc_api_base).rstrip("/"),
            timeout=settings.vc_timeout_s,
            transport=transport,
            trust_env=False,
        )
        self._service_token: str | None = None
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(self, identity: Identity, path: str, params: dict | None = None, timeout: float | None = None) -> Reply:
        return await self.request(identity, "GET", path, params=params, timeout=timeout)

    async def post(self, identity: Identity, path: str, json: Any = None, idem: str | None = None, timeout: float | None = None) -> Reply:
        return await self.request(identity, "POST", path, json=json, idem=idem, timeout=timeout)

    async def put(self, identity: Identity, path: str, json: Any = None, idem: str | None = None) -> Reply:
        return await self.request(identity, "PUT", path, json=json, idem=idem)

    async def delete(self, identity: Identity, path: str, idem: str | None = None) -> Reply:
        return await self.request(identity, "DELETE", path, idem=idem)

    async def request(
        self,
        identity: Identity,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        idem: str | None = None,
        timeout: float | None = None,
    ) -> Reply:
        if identity.readonly:
            token = await self._service()
            if token is None:
                return Reply(False, 401, None, "UNAUTHORIZED", "MCP 没有配置服务账号，只读模式无法访问系统平台")
        else:
            token = identity.token
        reply = await self._send(method, path, token, params, json, idem, timeout)
        if reply.status == 401 and identity.readonly:
            token = await self._service(refresh=True)
            if token:
                reply = await self._send(method, path, token, params, json, idem, timeout)
        return reply

    async def _send(self, method, path, token, params, json, idem, timeout) -> Reply:
        headers = {"Authorization": f"Bearer {token}"}
        if idem:
            headers["Idempotency-Key"] = idem
        clean = {key: value for key, value in (params or {}).items() if value is not None} or None
        try:
            response = await self._http.request(method, path, params=clean, json=json, headers=headers, timeout=timeout or settings.vc_timeout_s)
        except (httpx.TimeoutException, httpx.TransportError):
            return Reply(False, 0, None, "BACKEND_UNAVAILABLE", "系统平台没有响应")
        body = _body(response)
        if response.status_code < 400:
            return Reply(True, response.status_code, body)
        error = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}
        return Reply(
            False,
            response.status_code,
            body,
            str(error.get("code") or f"HTTP_{response.status_code}"),
            str(error.get("message") or ""),
            error.get("detail"),
        )

    async def _service(self, refresh: bool = False) -> str | None:
        async with self._lock:
            if self._service_token and not refresh:
                return self._service_token
            if not (settings.vc_tenant and settings.vc_username and settings.vc_password):
                return None
            try:
                response = await self._http.post(
                    "/auth/login",
                    json={"tenant": settings.vc_tenant, "username": settings.vc_username, "password": settings.vc_password},
                )
            except (httpx.TimeoutException, httpx.TransportError):
                return None
            body = _body(response)
            token = body.get("token") if response.status_code < 400 and isinstance(body, dict) else None
            self._service_token = str(token) if token else None
            return self._service_token


def _body(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text[:500]
