import json
from typing import Any


def turn_from_messages(messages: list[Any]) -> dict:
    uses: dict[str, dict] = {}
    order: list[str] = []
    texts: list[str] = []
    result_text = ""
    usage = None
    sdk_session_id = None
    failed = False
    errors: list[str] = []
    for message in messages:
        kind = type(message).__name__
        if kind == "ResultMessage":
            result_text = getattr(message, "result", None) or ""
            usage = getattr(message, "usage", None)
            sdk_session_id = getattr(message, "session_id", None)
            failed = bool(getattr(message, "is_error", False))
            errors = [str(item) for item in (getattr(message, "errors", None) or [])]
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            block_kind = type(block).__name__
            if block_kind == "TextBlock" and getattr(block, "text", None):
                texts.append(block.text)
            elif block_kind == "ToolUseBlock":
                tool_id = str(getattr(block, "id", None) or len(order))
                uses[tool_id] = {
                    "type": "tool",
                    "name": str(getattr(block, "name", "") or "tool"),
                    "args": _compact(getattr(block, "input", None)),
                    "result": "",
                }
                order.append(tool_id)
            elif block_kind == "ToolResultBlock":
                tool_id = str(getattr(block, "tool_use_id", None) or "")
                if tool_id not in uses and order:
                    tool_id = order[-1]
                if tool_id in uses:
                    uses[tool_id]["result"] = _compact(_result_text(block))
    text = (result_text or "\n".join(texts)).strip()
    if failed and not text:
        text = "；".join(errors) or "模型没有完成这次操作"
    tokens = _tokens(usage)
    return {
        "text": text,
        "blocks": [uses[key] for key in order],
        "tokens": tokens,
        "sdk_session_id": sdk_session_id,
        "failed": failed and not order and not text,
    }


def _tokens(usage: Any) -> list[int] | None:
    if not isinstance(usage, dict):
        return None
    incoming = usage.get("input_tokens")
    outgoing = usage.get("output_tokens")
    if incoming is None and outgoing is None:
        return None
    return [int(incoming or 0), int(outgoing or 0)]


def _result_text(block: Any) -> Any:
    content = getattr(block, "content", None)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return content


def _compact(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except TypeError:
            text = str(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
