import json
from typing import Any

from app.service.agent.actions import confirmation_card
from app.service.agent.cards import extract_choices, present_cards


class TurnBuilder:
    """Fold SDK messages into the stored turn, and into events the page can show immediately."""

    def __init__(self) -> None:
        self.uses: dict[str, dict] = {}
        self.order: list[str] = []
        self.actions: list[dict] = []
        self.displays: list[dict] = []
        self.texts: list[str] = []
        self.result_text = ""
        self.usage = None
        self.sdk_session_id = None
        self.failed = False
        self.errors: list[str] = []
        self._open: dict[int, dict] = {}
        self._segment: list[str] = []
        self._streamed = False
        self._cards: set[str] = set()
        self._shown: set[str] = set()
        self.stopped_early = False

    def feed(self, message: Any) -> list[dict]:
        kind = type(message).__name__
        if kind == "StreamEvent":
            return self._stream(getattr(message, "event", None))
        events: list[dict] = []
        if kind == "ResultMessage":
            self.result_text = getattr(message, "result", None) or ""
            self.usage = getattr(message, "usage", None)
            self.sdk_session_id = getattr(message, "session_id", None)
            self.failed = bool(getattr(message, "is_error", False))
            self.errors = [str(item) for item in (getattr(message, "errors", None) or [])]
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            return events
        streamed = self._streamed
        self._streamed = False
        if any(type(block).__name__ == "TextBlock" and getattr(block, "text", None) for block in content):
            self._segment.clear()
        for block in content:
            block_kind = type(block).__name__
            if block_kind == "TextBlock" and getattr(block, "text", None):
                self.texts.append(block.text)
                if not streamed:
                    events.append({"type": "text", "text": block.text})
            elif block_kind == "ToolUseBlock":
                tool_id = str(getattr(block, "id", None) or len(self.order))
                raw = getattr(block, "input", None)
                args = _compact(raw)
                if tool_id in self.uses:
                    self._remember(tool_id, raw)
                    if args and args != self.uses[tool_id]["args"]:
                        self.uses[tool_id]["args"] = args
                        events.append({"type": "tool_args", "id": tool_id, "args": args})
                    continue
                self.uses[tool_id] = {
                    "type": "tool",
                    "name": str(getattr(block, "name", "") or "tool"),
                    "args": args,
                    "result": "",
                }
                self._remember(tool_id, raw)
                self.order.append(tool_id)
                events.append({"type": "tool", "id": tool_id, "name": self.uses[tool_id]["name"], "args": args})
            elif block_kind == "ToolResultBlock":
                tool_id = str(getattr(block, "tool_use_id", None) or "")
                if tool_id not in self.uses and self.order:
                    tool_id = self.order[-1]
                if tool_id in self.uses:
                    raw = _result_text(block)
                    result = _compact(raw)
                    self.uses[tool_id]["result"] = result
                    events.append({"type": "tool_result", "id": tool_id, "result": result})
                    source = raw if isinstance(raw, str) else result
                    card = self._pending(tool_id, source)
                    if card:
                        events.append({"type": "action", "action": card})
                    for shown in self._show(tool_id, source):
                        events.append({"type": shown["type"], shown["type"]: shown})
        return events

    def finish(self) -> dict:
        if self._segment:
            self.texts.append("".join(self._segment))
            self._segment.clear()
        text = self._answer_text()
        text, choice = extract_choices(text)
        if self.failed and not text:
            text = "；".join(self.errors) or "模型没有完成这次操作"
        blocks = []
        for key in self.order:
            item = dict(self.uses[key])
            item.pop("call", None)
            blocks.append(item)
        blocks.extend(self.displays)
        if choice:
            blocks.append(choice)
        blocks.extend(self.actions)
        return {
            "text": text,
            "blocks": blocks,
            "tokens": _tokens(self.usage),
            "sdk_session_id": self.sdk_session_id,
            "failed": self.failed and not self.order and not text,
        }

    def hit_turn_limit(self) -> bool:
        blob = "\n".join([self.result_text or "", *self.errors])
        return "maximum number of turns" in blob.lower()

    def _answer_text(self) -> str:
        body = "\n".join(item for item in self.texts if item).strip()
        note = (self.result_text or "").strip()
        if _is_turn_limit(note):
            note = ""
            self.failed = False
        text = note or body
        if text:
            return text
        if self.hit_turn_limit() or self.stopped_early:
            return "工具调用已经用完，结论还没有写出来。"
        return ""

    def _remember(self, tool_id: str, raw: Any) -> None:
        if tool_id not in self.uses:
            return
        parsed = _json_or_text(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            self.uses[tool_id]["call"] = parsed

    def _show(self, tool_id: str, result_text: str) -> list[dict]:
        if tool_id in self._shown:
            return []
        cards = present_cards(self.uses[tool_id]["name"], result_text)
        if not cards:
            return []
        self._shown.add(tool_id)
        self.displays.extend(cards)
        return cards

    def _pending(self, tool_id: str, result_text: str) -> dict | None:
        if tool_id in self._cards:
            return None
        card = confirmation_card(self.uses[tool_id]["name"], self.uses[tool_id].get("call"), result_text)
        if card is None:
            return None
        self._cards.add(tool_id)
        self.actions.append(card)
        return card

    def _stream(self, event: Any) -> list[dict]:
        if not isinstance(event, dict):
            return []
        kind = event.get("type")
        if kind == "content_block_start":
            return self._block_start(event)
        if kind == "content_block_delta":
            return self._block_delta(event)
        if kind == "content_block_stop":
            return self._block_stop(event)
        return []

    def _block_start(self, event: dict) -> list[dict]:
        block = event.get("content_block")
        if not isinstance(block, dict):
            return []
        index = int(event.get("index") or 0)
        if block.get("type") == "text" and block.get("text"):
            self._streamed = True
            self._segment.append(str(block["text"]))
            return [{"type": "text", "text": str(block["text"])}]
        if block.get("type") != "tool_use":
            return []
        tool_id = str(block.get("id") or len(self.order))
        args = _compact(block.get("input")) if block.get("input") else ""
        self._open[index] = {"kind": "tool", "id": tool_id, "buf": ""}
        if tool_id in self.uses:
            self._remember(tool_id, block.get("input"))
            return []
        self.uses[tool_id] = {
            "type": "tool",
            "name": str(block.get("name") or "tool"),
            "args": args,
            "result": "",
        }
        self._remember(tool_id, block.get("input"))
        self.order.append(tool_id)
        return [{"type": "tool", "id": tool_id, "name": self.uses[tool_id]["name"], "args": args}]

    def _block_delta(self, event: dict) -> list[dict]:
        delta = event.get("delta")
        if not isinstance(delta, dict):
            return []
        if delta.get("type") == "text_delta" and delta.get("text"):
            self._streamed = True
            self._segment.append(str(delta["text"]))
            return [{"type": "text", "text": str(delta["text"])}]
        if delta.get("type") != "input_json_delta":
            return []
        opened = self._open.get(int(event.get("index") or 0))
        if opened is None:
            return []
        opened["buf"] += str(delta.get("partial_json") or "")
        return []

    def _block_stop(self, event: dict) -> list[dict]:
        opened = self._open.pop(int(event.get("index") or 0), None)
        if opened is None or opened.get("kind") != "tool":
            return []
        tool_id = opened["id"]
        if tool_id not in self.uses or not opened.get("buf"):
            return []
        parsed = _json_or_text(opened["buf"])
        self._remember(tool_id, parsed)
        args = _compact(parsed)
        if not args or args == self.uses[tool_id]["args"]:
            return []
        self.uses[tool_id]["args"] = args
        return [{"type": "tool_args", "id": tool_id, "args": args}]


def _is_turn_limit(text: str) -> bool:
    return "maximum number of turns" in text.lower()


def turn_from_messages(messages: list[Any]) -> dict:
    builder = TurnBuilder()
    for message in messages:
        builder.feed(message)
    return builder.finish()


def _tokens(usage: Any) -> list[int] | None:
    if not isinstance(usage, dict):
        return None
    incoming = usage.get("input_tokens")
    outgoing = usage.get("output_tokens")
    if incoming is None and outgoing is None:
        return None
    return [int(incoming or 0), int(outgoing or 0)]


def _json_or_text(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


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
