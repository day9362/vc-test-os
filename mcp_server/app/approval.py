import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.result import fail, forbidden, need_approval
from app.state import Ctx, get_store
from app.text import now_ms

RISK: dict[tuple[str, str], str] = {
    ("vc_plan", "publish"): "medium",
    ("vc_operate", "power_on"): "medium",
    ("vc_operate", "maintenance"): "medium",
    ("vc_operate", "slot_load"): "medium",
    ("vc_operate", "slot_start"): "medium",
    ("vc_operate", "slot_test"): "medium",
    ("vc_operate", "production_start"): "medium",
    ("vc_operate", "sim_speed"): "medium",
    ("vc_operate", "power_off"): "high",
    ("vc_operate", "reset"): "high",
    ("vc_operate", "slot_abort"): "high",
    ("vc_operate", "production_stop"): "high",
    ("vc_operate", "sim_scenario"): "high",
    ("vc_operate", "sim_fault"): "high",
    ("vc_quality", "ack_all"): "medium",
    ("vc_quality", "apply_compensation"): "medium",
}


def risk_of(tool: str, action: str) -> str:
    return RISK.get((tool, action), "low")


def sign(confirm_id: str, secret: str | None = None) -> str:
    key = (secret if secret is not None else settings.mcp_approval_secret).encode()
    return hmac.new(key, confirm_id.encode(), hashlib.sha256).hexdigest()


@dataclass
class Preview:
    sentence: str
    effects: list[str] = field(default_factory=list)
    precheck: Any = None
    args: dict | None = None


class MemoryStore:
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, str]] = {}

    async def put(self, key: str, value: str, ttl: int) -> None:
        self._items[key] = (time.monotonic() + ttl, value)

    async def get(self, key: str) -> str | None:
        found = self._items.get(key)
        if found is None or found[0] < time.monotonic():
            self._items.pop(key, None)
            return None
        return found[1]

    async def take(self, key: str) -> str | None:
        value = await self.get(key)
        self._items.pop(key, None)
        return value

    async def aclose(self) -> None:
        return None


class RedisStore:
    def __init__(self, url: str) -> None:
        from redis.asyncio import from_url

        self._redis = from_url(url, decode_responses=True)

    async def put(self, key: str, value: str, ttl: int) -> None:
        await self._redis.set(key, value, ex=ttl)

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def take(self, key: str) -> str | None:
        # 旧版 Redis 没有 GETDEL，用 GET + DEL 模拟一次性取出。
        value = await self._redis.get(key)
        if value is None:
            return None
        await self._redis.delete(key)
        return value

    async def aclose(self) -> None:
        await self._redis.aclose()


Execute = Callable[[dict, str | None], Awaitable[dict]]
PreviewFn = Callable[[], Awaitable["Preview | dict"]]


async def guarded(
    c: Ctx,
    tool: str,
    action: str,
    args: dict,
    *,
    confirm_id: str | None,
    approval: str | None,
    preview: PreviewFn,
    execute: Execute,
) -> dict:
    """低风险直接执行；中高风险先登记等页面批准，批准后只按登记时的参数执行一次。"""
    if c.identity.readonly:
        return forbidden()
    risk = risk_of(tool, action)
    if risk == "low":
        return await execute(args, None)
    if confirm_id or approval:
        return await _approved(c, tool, action, confirm_id or "", approval or "", execute)
    checked = await preview()
    if isinstance(checked, dict):
        return checked
    stored = checked.args if checked.args is not None else args
    confirm = "cf_" + secrets.token_hex(12)
    record = {"user": c.identity.user_id, "tool": tool, "action": action, "args": stored}
    await get_store().put(_key(confirm), json.dumps(record, ensure_ascii=False), settings.approval_ttl_s)
    card = {
        "confirm_id": confirm,
        "tool": tool,
        "action": action,
        "arguments": stored,
        "risk": risk,
        "sentence": checked.sentence,
        "effects": checked.effects,
        "precheck": checked.precheck,
        "expires_at": now_ms() + settings.approval_ttl_s * 1000,
    }
    return need_approval(checked.sentence, card)


async def _approved(c: Ctx, tool: str, action: str, confirm_id: str, approval: str, execute: Execute) -> dict:
    if not settings.mcp_approval_secret:
        return _invalid("MCP 没有配置批准密钥，不能执行需要批准的操作。")
    if not confirm_id or not approval or not hmac.compare_digest(sign(confirm_id), approval):
        return _invalid("批准凭证不对。需要用户在页面上点批准。")
    store = get_store()
    raw = await store.get(_key(confirm_id))
    if raw is None:
        return _invalid("这次批准已经过期或已经执行过。")
    record = json.loads(raw)
    if record.get("user") != c.identity.user_id:
        return _invalid("批准人和发起人不是同一个用户。")
    if record.get("tool") != tool or record.get("action") != action:
        return _invalid("批准的操作和这次调用的不一致。")
    if await store.take(_key(confirm_id)) is None:
        return _invalid("这次批准已经执行过。")
    return await execute(record.get("args") or {}, confirm_id)


def _invalid(summary: str) -> dict:
    return fail(summary, "APPROVAL_INVALID", status=403)


def _key(confirm_id: str) -> str:
    return f"mcp:confirm:{confirm_id}"


def pick(values: dict, *exclude: str) -> dict:
    """工具参数里去掉空值和控制参数，作为登记与执行的参数。"""
    skip = {"action", "confirm_id", "approval", *exclude}
    return {key: _plain(value) for key, value in values.items() if key not in skip and value is not None}


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value
