import base64
import hashlib
import json
from contextvars import ContextVar
from dataclasses import dataclass

from fastmcp.server.dependencies import get_http_headers


@dataclass(frozen=True)
class Identity:
    """带用户令牌的是用户模式，可以用写工具；没有令牌的外部客户端是只读模式。"""

    token: str | None = None

    @property
    def readonly(self) -> bool:
        return not self.token

    @property
    def user_id(self) -> str:
        if not self.token:
            return "readonly"
        sub = _jwt_sub(self.token)
        return sub or "t:" + hashlib.sha256(self.token.encode()).hexdigest()[:16]


_forced: ContextVar[Identity | None] = ContextVar("forced_identity", default=None)


def force_identity(identity: Identity | None):
    return _forced.set(identity)


def current_identity() -> Identity:
    forced = _forced.get()
    if forced is not None:
        return forced
    headers = get_http_headers(include={"authorization"})
    scheme, _, token = (headers.get("authorization") or "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return Identity(token.strip())
    return Identity()


def _jwt_sub(token: str) -> str | None:
    # 只用来比对批准前后是不是同一个人，签名由后端校验。
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return None
    sub = payload.get("sub") if isinstance(payload, dict) else None
    return str(sub) if sub else None
