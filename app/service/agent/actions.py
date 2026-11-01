import hashlib
import hmac
import json
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.errors import AppError

WRITE_TOOLS = {"vc_plan", "vc_operate", "vc_quality"}


def tool_name(name: str) -> str:
    return (name or "").split("__")[-1]


def sign(confirm_id: str, secret: str | None = None) -> str:
    key = (secret if secret is not None else settings.mcp_approval_secret).encode()
    return hmac.new(key, confirm_id.encode(), hashlib.sha256).hexdigest()


def confirmation_card(name: str, arguments: dict | None, result_text: str) -> dict | None:
    """识别 MCP 返回的 APPROVAL_REQUIRED，登记为页面上的待确认操作。"""
    payload = _object(result_text)
    if payload is None or payload.get("ok") is not False:
        return None
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    if error.get("code") != "APPROVAL_REQUIRED":
        return None
    approval = payload.get("approval") if isinstance(payload.get("approval"), dict) else {}
    confirm_id = str(approval.get("confirm_id") or "")
    action = str(approval.get("action") or (arguments or {}).get("action") or "")
    if not confirm_id or not action:
        return None
    return {
        "type": "action",
        "id": f"act-{uuid4().hex[:8]}",
        "name": tool_name(name),
        "desc": str(approval.get("sentence") or payload.get("summary") or "需要确认后执行").rstrip("。"),
        "arguments": {"action": action, "confirm_id": confirm_id},
        "status": "pending",
        "result": "",
        "risk": str(approval.get("risk") or "medium"),
        "effects": list(approval.get("effects") or []),
    }


async def strip_model_confirmation(input_data: Any, tool_use_id: str | None = None, context: Any = None) -> dict:
    """模型自己带上的 confirm_id / approval 不算数，调用前一律去掉。"""
    tool_input = input_data.get("tool_input") if isinstance(input_data, dict) else None
    if not isinstance(tool_input, dict):
        return {}
    if "confirm_id" not in tool_input and "approval" not in tool_input:
        return {}
    updated = {key: value for key, value in tool_input.items() if key not in {"confirm_id", "approval"}}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": updated,
        }
    }


async def call_confirmed(name: str, arguments: dict | None, user_token: str) -> dict:
    short = tool_name(name)
    if short not in WRITE_TOOLS:
        raise AppError(422, "NOT_A_WRITE", "这个操作不能从待确认列表执行")
    args = arguments or {}
    confirm_id = str(args.get("confirm_id") or "")
    action = str(args.get("action") or "")
    if not confirm_id or not action:
        raise AppError(422, "NOT_A_WRITE", "缺少确认编号或动作")
    if not settings.mcp_approval_secret:
        raise AppError(503, "APPROVAL_SECRET_MISSING", "没有配置批准密钥")
    if not user_token:
        raise AppError(401, "UNAUTHORIZED", "未登录")
    payload = {"action": action, "confirm_id": confirm_id, "approval": sign(confirm_id)}
    try:
        parsed = await _call_mcp(short, payload, user_token)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(502, "MCP_FAILED", "系统平台 MCP 没有连上，这次没有执行") from exc
    return parsed


async def _call_mcp(name: str, arguments: dict, user_token: str) -> dict:
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    headers = {"Authorization": f"Bearer {user_token}"}
    async with create_mcp_http_client(headers=headers) as http:
        async with Client(
            streamable_http_client(settings.mcp_url, http_client=http),
            read_timeout_seconds=60,
        ) as client:
            result = await client.call_tool(name, arguments, read_timeout_seconds=60)
    if getattr(result, "is_error", False):
        parsed_error = _object(_content_text(result)) or {}
        raise AppError(502, "MCP_FAILED", str(parsed_error.get("summary") or "系统平台没有完成这次操作"))
    parsed = _structured(result)
    if parsed is None:
        raise AppError(502, "MCP_FAILED", "系统平台没有返回可识别的结果，不确定这次有没有执行")
    return parsed


def _object(text: str) -> dict | None:
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _structured(result: Any) -> dict | None:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    return _object(_content_text(result))


def _content_text(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(str(text))
        elif isinstance(item, dict) and item.get("text"):
            parts.append(str(item["text"]))
    return "\n".join(parts)
