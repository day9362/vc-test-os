import json
import re
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import settings
from app.service.reports.analysis_math import item_sort_key
from app.core.errors import AppError

_NUMBER = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])")
_ITEM = re.compile(r"Temp_T\d+(?:-T\d+)?|power_w")
_PROMPT = """你是测试分析总结。下面这份 JSON 是后端已经算好的卡限项分析。
只根据它写 4 到 7 句中文，放进 lines。
先写这一批有多少片、不合格多少片。再按 JSON 里 items 的顺序逐项写均值、极差、最小值、最大值、上限或下限、超上限或超下限的片数、偏移、上限裕量或下限裕量。顺序是温差测点从小到大，例如 Temp_T0-T1、Temp_T1-T2、Temp_T1-T4，功率放在温差后面。不要按不合格片数打乱这个顺序。温度写成 ℃，功率写成 W。
不合格按 fail_groups 写。先写测了多少片。单项不合格写该项和片数。多项不合格写这一组项名和片数。各组片数加起来等于不合格片数，不要把同一片上的各项再加一次。
相关性只写同一项在各批次、各机台或各槽位之间的均值和极差，指出哪一组更高或更散。不要写两个不同项之间的相关系数。
中止和未保留只写片数。
用词只能从下面这套里选，同一个意思不要换词：
片、不合格、均值、极差、重复性、最大值、最小值、上限、下限、超上限、超下限、偏上限、偏下限、居中、单侧限、上限裕量、下限裕量、相关性、时间顺序、持平、后半段升高、后半段降低、片数不足。温度数字后面写 ℃，功率数字后面写 W。不要把最大值写成最大，不要把最小值写成最小。
不要写高限、低限、偏高限、偏低限、超出上限、超出下限、样品、超限。
每个数字必须原样来自 JSON，不要换算，不要另行四舍五入，不要估算。
可以写出 JSON 里的批次号、机台号和项名。机台槽位写成「M01 槽1」，不要写成 M01#1。某一槽片数不够时，只写该槽的极差和「其余槽位片数不足」，不要写更大。
返回 json，格式为 {"lines": ["第一句", "第二句"]}。
"""
_WORDS = (
    ("片样品", "片"),
    ("偏高限", "偏上限"),
    ("偏低限", "偏下限"),
    ("超高限", "超上限"),
    ("超低限", "超下限"),
    ("超出上限", "超上限"),
    ("超出下限", "超下限"),
    ("超过上限", "超上限"),
    ("超过下限", "超下限"),
    ("高限", "上限"),
    ("低限", "下限"),
    ("上限不合格", "超上限"),
    ("下限不合格", "超下限"),
    ("偏移偏上限", "偏上限"),
    ("偏移偏下限", "偏下限"),
    ("偏移居中", "居中"),
    ("重复性标准差", "重复性"),
    ("共同不合格", "一起不合格"),
    ("样品", "片"),
)
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
            lines.append(_explain(unify_words(line)))
    if not lines:
        raise AppError(502, "AGENT_FAILED", "总结里的数字和报告对不上")
    return polish_summary_lines(lines)


async def _post_summary(client: httpx.AsyncClient, body: dict) -> httpx.Response:
    return await client.post(
        chat_completions_url(settings.anthropic_base_url),
        headers={"Authorization": f"Bearer {settings.anthropic_api_key}"},
        json=body,
    )


async def request_summary(payload: dict, model: str | None = None) -> tuple[str, int, int, str]:
    if not settings.anthropic_base_url or not settings.anthropic_api_key:
        raise AppError(503, "MODEL_NOT_CONFIGURED", "没有配置第三方模型地址或密钥")
    model = (model or settings.anthropic_model or "deepseek-flash").strip()
    body = {
        "model": model,
        "messages": [{"role": "user", "content": _PROMPT + json.dumps(payload, ensure_ascii=False)}],
        "response_format": {"type": "json_object"},
        "max_tokens": 2000,
        "thinking": {"type": "disabled"},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await _post_summary(client, body)
            if response.status_code == 400:
                body.pop("thinking", None)
                body["max_tokens"] = 8000
                response = await _post_summary(client, body)
            elif response.status_code < 400 and not _message_text(response):
                body["max_tokens"] = 8000
                response = await _post_summary(client, body)
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


def polish_summary_lines(lines: list[str]) -> list[str]:
    polished = [_measure_unit(_rewrite_slot(line)) for line in lines]
    slots = [index for index, line in enumerate(polished) if len(_ITEM.findall(line)) == 1]
    ordered = sorted(slots, key=lambda index: item_sort_key(_ITEM.search(polished[index]).group(0)))
    result = list(polished)
    for slot, source in zip(slots, ordered):
        result[slot] = polished[source]
    return result


def _rewrite_slot(line: str) -> str:
    if not re.search(r"M\d+#\d+槽位", line):
        return line
    line = re.sub(r"(M\d+)#(\d+)槽位", r"\1 槽\2 的 ", line)
    line = line.replace("更大，其余槽位片数不足", "。其余槽位片数不足")
    return re.sub(r"(Temp_T\d+(?:-T\d+)?|power_w)(?=极差|均值)", r"\1 ", line)


def _measure_unit(line: str) -> str:
    names = _ITEM.findall(line)
    if len(names) != 1:
        return line
    unit = " W" if names[0] == "power_w" else " ℃"

    def place(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}{unit}"

    return re.sub(r"(?<!超)(上限裕量|下限裕量|均值|极差|最大值|最小值|上限|下限)\s*(-?\d+(?:\.\d+)?)(?!\s*(?:℃|W|片))", place, line)


def unify_words(line: str) -> str:
    for source, target in _WORDS:
        line = line.replace(source, target)
    line = re.sub(r"最小(?!值|的)", "最小值", line)
    line = re.sub(r"最大(?!值|的)", "最大值", line)
    return line


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
