import json
import re
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import settings
from app.core.errors import AppError

_NUMBER = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])")
_PROMPT = """你是批次报告的总结。下面这份 JSON 是后端已经算好的结果。
只根据它写 3 到 6 句中文，放进 lines。
每个数字必须原样来自 JSON，不要换算，不要另行四舍五入，不要估算。
批次个数用 batch_count。可以写出 JSON 里的批次号和机台号。
返回 json，格式为 {"lines": ["第一句", "第二句"]}。
"""
_GLOSS = (
    ("top_fail_count", "主要不合格项片数"),
    ("machine_count", "机台数"),
    ("batch_count", "批次数"),
    ("plan_version", "方案版本"),
    ("yield_rate", "良率"),
    ("rc_mean", "Rc 均值"),
    ("rc_sd", "Rc 标准差"),
    ("cpk_t01", "T0−T1 的 Cpk"),
    ("usl_t01", "T0−T1 上限"),
    ("top_fail", "主要不合格项"),
    ("machine_id", "机台"),
    ("batch_id", "批次"),
    ("plan_id", "方案"),
    ("count", "片数"),
    ("tested", "测试数"),
    ("passed", "合格"),
    ("failed", "不合格"),
    ("aborted", "中止"),
    ("n", "片数"),
)


def chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/anthropic"):
        base = base[: -len("/anthropic")]
    return f"{base}/chat/completions"


def grounded_lines(text: str, payload: dict) -> list[str]:
    data = _object(text)
    raw = data.get("lines")
    if not isinstance(raw, list):
        raise AppError(502, "AGENT_FAILED", "模型没有返回总结")
    allowed = _numbers(payload)
    names = _texts(payload)
    lines = []
    for item in raw:
        line = str(item).strip()
        if not line:
            continue
        if _line_ok(line, allowed, names):
            lines.append(_explain(line))
    if not lines:
        raise AppError(502, "AGENT_FAILED", "总结里的数字和报告对不上")
    return lines


async def request_summary(payload: dict) -> tuple[str, int, int, str]:
    if not settings.anthropic_base_url or not settings.anthropic_api_key:
        raise AppError(503, "MODEL_NOT_CONFIGURED", "没有配置第三方模型地址或密钥")
    model = settings.anthropic_model or "deepseek-flash"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": _PROMPT + json.dumps(payload, ensure_ascii=False)}],
        "response_format": {"type": "json_object"},
        "max_tokens": 2000,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                chat_completions_url(settings.anthropic_base_url),
                headers={"Authorization": f"Bearer {settings.anthropic_api_key}"},
                json=body,
            )
            if response.status_code < 400 and not _message_text(response):
                response = await client.post(
                    chat_completions_url(settings.anthropic_base_url),
                    headers={"Authorization": f"Bearer {settings.anthropic_api_key}"},
                    json=body,
                )
    except httpx.HTTPError as exc:
        raise AppError(502, "AGENT_FAILED", "总结请求没有完成") from exc
    if response.status_code >= 400:
        raise AppError(502, "AGENT_FAILED", _provider_message(response))
    content = _message_text(response)
    if content is None:
        raise AppError(502, "AGENT_FAILED", "模型没有返回总结")
    try:
        data = response.json()
        usage = data.get("usage") or {}
        model_name = str(data.get("model") or model)
    except ValueError as exc:
        raise AppError(502, "AGENT_FAILED", "模型没有返回总结") from exc
    return content, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), model_name


def _message_text(response: httpx.Response) -> str | None:
    try:
        message = response.json()["choices"][0]["message"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str) and content.strip():
        return content
    return None


def _object(text: str) -> dict:
    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    start = raw.find("{")
    if start < 0:
        raise AppError(502, "AGENT_FAILED", "模型没有返回总结")
    try:
        data, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError as exc:
        raise AppError(502, "AGENT_FAILED", "模型没有返回总结") from exc
    if not isinstance(data, dict):
        raise AppError(502, "AGENT_FAILED", "模型没有返回总结")
    return data


def _numbers(value: object, found: set[str] | None = None) -> set[str]:
    found = set() if found is None else found
    if isinstance(value, bool):
        return found
    if isinstance(value, int):
        found.add(str(value))
    elif isinstance(value, float):
        text = json.dumps(value)
        found.add(text)
        if "." in text:
            found.add(text.rstrip("0").rstrip("."))
    elif isinstance(value, dict):
        for item in value.values():
            _numbers(item, found)
    elif isinstance(value, list):
        for item in value:
            _numbers(item, found)
    return found


def _texts(value: object, found: list[str] | None = None) -> list[str]:
    found = [] if found is None else found
    if isinstance(value, str) and len(value) >= 2:
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            _texts(item, found)
    elif isinstance(value, list):
        for item in value:
            _texts(item, found)
    return found


def _explain(line: str) -> str:
    for word, gloss in _GLOSS:
        line = re.sub(rf"\b{word}\b(?![（(])", f"{word}（{gloss}）", line)
    return line


def _line_ok(line: str, allowed: set[str], names: list[str]) -> bool:
    masked = line.replace(",", "")
    for name in sorted(names, key=len, reverse=True):
        masked = masked.replace(name, " ")
    for token in _NUMBER.findall(masked):
        if not _known(token, allowed):
            return False
    return True


def _known(token: str, allowed: set[str]) -> bool:
    if token in allowed:
        return True
    try:
        value = Decimal(token)
    except InvalidOperation:
        return False
    for item in allowed:
        try:
            if Decimal(item) == value:
                return True
        except InvalidOperation:
            continue
    return False


def _provider_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "总结请求没有完成"
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return str(message or "总结请求没有完成")
