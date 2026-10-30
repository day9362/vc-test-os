import json
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.errors import AppError

# These tools refuse until human_confirmed is true. cluster_plan dispatch has no such switch and runs immediately.
GATED = {
    "cluster_control": None,
    "cluster_compensation": {"apply"},
    "cluster_product": {"requeue"},
}


def tool_name(name: str) -> str:
    return (name or "").split("__")[-1]


def is_gated(name: str, arguments: dict | None) -> bool:
    short = tool_name(name)
    allowed = GATED.get(short)
    if short not in GATED:
        return False
    if allowed is None:
        return True
    return str((arguments or {}).get("action") or "") in allowed


def confirmation_card(name: str, arguments: dict | None, result_text: str) -> dict | None:
    args = arguments if isinstance(arguments, dict) else {}
    if not is_gated(name, args):
        return None
    payload = _object(result_text)
    if payload is None or payload.get("ok") is not False:
        return None
    summary = str(payload.get("summary") or "")
    detail = str(payload.get("detail") or "")
    if "同意" not in f"{summary}{detail}":
        return None
    kept = {key: value for key, value in args.items() if key != "human_confirmed"}
    return {
        "type": "action",
        "id": f"act-{uuid4().hex[:8]}",
        "name": tool_name(name),
        "desc": _sentence(detail, summary),
        "arguments": kept,
        "status": "pending",
        "result": "",
        "risk": _risk(tool_name(name), args),
    }


async def strip_model_confirmation(input_data: Any, tool_use_id: str | None = None, context: Any = None) -> dict:
    """模型自己带上的 human_confirmed 不算数，调用前一律改成 false。"""
    tool_input = input_data.get("tool_input") if isinstance(input_data, dict) else None
    if not isinstance(tool_input, dict):
        return {}
    name = str(input_data.get("tool_name") or "")
    if not is_gated(name, tool_input):
        return {}
    updated = {key: value for key, value in tool_input.items() if key != "human_confirmed"}
    updated["human_confirmed"] = False
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": updated,
        }
    }


async def call_confirmed(name: str, arguments: dict | None) -> dict:
    if not is_gated(name, arguments):
        raise AppError(422, "NOT_A_WRITE", "这个操作不能从待确认列表执行")
    payload = {key: value for key, value in (arguments or {}).items() if key != "human_confirmed"}
    payload["human_confirmed"] = True
    try:
        from mcp import Client

        async with Client(settings.mcp_url, read_timeout_seconds=60) as client:
            result = await client.call_tool(tool_name(name), payload, read_timeout_seconds=60)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(502, "MCP_FAILED", "集群服务没有连上，这次没有执行") from exc
    if getattr(result, "is_error", False):
        parsed_error = _object(_content_text(result)) or {}
        raise AppError(502, "MCP_FAILED", str(parsed_error.get("summary") or "集群没有完成这次操作"))
    parsed = _structured(result)
    if parsed is None:
        raise AppError(502, "MCP_FAILED", "集群没有返回可识别的结果，不确定这次有没有执行")
    return parsed


def _risk(name: str, arguments: dict) -> str:
    action = str(arguments.get("action") or "")
    if name == "cluster_control" and action == "power" and arguments.get("power_state") == "off":
        return "high"
    if name == "cluster_control" and action == "abort":
        return "high"
    if name == "cluster_control" and action == "production" and arguments.get("production_command") == "stop":
        return "high"
    if name == "cluster_control" and action in {"reset", "init"}:
        return "high"
    if name in {"cluster_compensation", "cluster_product"}:
        return "high"
    return "low"


def _sentence(detail: str, summary: str) -> str:
    marker = "请先向用户说明："
    if marker in detail:
        rest = detail.split(marker, 1)[1]
        stop = rest.find("。")
        if stop > 0:
            return rest[:stop]
    if summary:
        return summary.rstrip("。")
    stop = detail.find("。")
    return (detail[:stop] if stop > 0 else detail) or "需要确认后执行"


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
