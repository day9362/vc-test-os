import json
import re

from pydantic import ValidationError

from app.core.errors import AppError
from app.models.dto.test_plan import PlanBody, UsageOut
from app.service.agent.prompts import DRAFT_PROMPT
from app.service.agent.runtime import run_turn

_DEFAULTS = {
    "start_temp_c": 45,
    "duration_s": 180,
    "sample_period_s": 1,
    "power_w": 2.5,
    "force_g": 100,
    "orientation": 0,
    "overtemp_c": 80,
    "ambient_low_c": 23,
    "ambient_high_c": 27,
}


async def generate_draft(text: str) -> tuple[PlanBody, list[str], UsageOut]:
    turn = await run_turn("agent.plan", text, None, system=DRAFT_PROMPT, allowed_tools=[], max_turns=4)
    body, notes = plan_from_reply(turn.get("text") or "")
    tokens = turn.get("tokens") or [0, 0]
    return body, notes, UsageOut(input=int(tokens[0]), output=int(tokens[1]))


def plan_from_reply(text: str) -> tuple[PlanBody, list[str]]:
    data = _json_object(text)
    notes = _notes(data.pop("notes", []))
    power = _number(data.get("power_w"), _DEFAULTS["power_w"])
    duration = int(_number(data.get("duration_s"), _DEFAULTS["duration_s"]))
    if data.get("limits"):
        data["limits"] = _normalize_limits(data["limits"])
    else:
        data["limits"] = _standard_limits(power, duration)
        notes.append("判定项未写全，已按功率和时长补上")
    for key, value in _DEFAULTS.items():
        if data.get(key) is None or data.get(key) == "":
            data[key] = value
    data["name"] = str(data.get("name") or "未命名草稿").strip()[:18] or "未命名草稿"
    data["duration_s"] = int(_number(data.get("duration_s"), _DEFAULTS["duration_s"]))
    data["orientation"] = int(_number(data.get("orientation"), 0))
    try:
        body = PlanBody.model_validate(data)
    except ValidationError as exc:
        raise AppError(502, "AGENT_FAILED", "模型没有返回可保存的方案") from exc
    return body, notes


def _json_object(text: str) -> dict:
    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    start = raw.find("{")
    if start < 0:
        raise AppError(502, "AGENT_FAILED", "模型没有返回可保存的方案")
    try:
        data, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError as exc:
        raise AppError(502, "AGENT_FAILED", "模型没有返回可保存的方案") from exc
    if not isinstance(data, dict):
        raise AppError(502, "AGENT_FAILED", "模型没有返回可保存的方案")
    return data


def _notes(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_limits(raw: object) -> list[dict]:
    rows = raw
    if isinstance(raw, dict):
        rows = []
        for item, rule in raw.items():
            if isinstance(rule, dict):
                rows.append({"item": item, **rule})
            else:
                rows.append({"item": item, "high": rule})
    if not isinstance(rows, list):
        raise AppError(502, "AGENT_FAILED", "模型没有返回可保存的方案")
    limits = []
    for rule in rows:
        if not isinstance(rule, dict) or not rule.get("item"):
            continue
        limits.append({
            "item": str(rule["item"]),
            "low": None if rule.get("low") is None else _number(rule.get("low"), 0),
            "high": None if rule.get("high") is None else _number(rule.get("high"), 0),
            "unit": str(rule.get("unit") or ""),
            "skipped": _flag(rule.get("skipped")),
        })
    if not limits:
        raise AppError(502, "AGENT_FAILED", "模型没有返回可保存的方案")
    return limits


def _standard_limits(power: float, duration: int) -> list[dict]:
    power_limit = {"item": "power_w", "low": round(power - 0.1, 2), "high": round(power + 0.1, 2), "unit": "W", "skipped": False}
    if duration <= 30:
        return [power_limit]
    t01 = 3.4 if power > 3 else 2.8
    t1x = 4.8 if power > 3 else 4.0
    limits = [{"item": "Temp_T0-T1", "low": 0, "high": t01, "unit": "℃", "skipped": False}]
    limits += [
        {"item": f"Temp_T1-T{index + 2}", "low": 0, "high": t1x, "unit": "℃", "skipped": index > 10}
        for index in range(13)
    ]
    limits.append(power_limit)
    return limits


def _number(value: object, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _flag(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)
