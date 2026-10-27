import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

_FENCE = re.compile(r"```vc-choices\s*([\s\S]*?)```", re.IGNORECASE)
_ROW_LIMIT = 20
_TABLE_MIN = 6
_POINT_LIMIT = 80
_FILE_LIMIT = 8_000_000

_TABLES = {
    "runs": ("测试记录", [("run_id", "记录"), ("machine_id", "机台"), ("serial_number", "序列号"), ("status", "状态"), ("passed", "合格")]),
    "machines": ("机台", [("machine_id", "机台"), ("status", "状态"), ("comm_status", "通信"), ("plan_id", "方案"), ("plan_version", "版本"), ("queue_remaining", "排队"), ("speed", "倍率")]),
    "products": ("产品", [("serial_number", "序列号"), ("model", "型号"), ("batch_id", "批次"), ("state", "状态"), ("golden", "标准样品"), ("test_count", "已测次数")]),
    "batches": ("批次", [("batch_id", "批次"), ("model", "型号"), ("count", "数量"), ("defect_ratio", "缺陷比例")]),
    "plans": ("方案", [("plan_id", "方案"), ("name", "名称"), ("version", "版本"), ("power_w", "功率"), ("duration_s", "时长"), ("force_g", "压紧力")]),
    "models": ("型号", [("model", "型号"), ("power_w", "功率"), ("resistance_mean", "热阻均值")]),
}


def result_roots() -> list[Path]:
    roots = []
    if os.environ.get("MCP_RESULT_DIR"):
        roots.append(Path(os.environ["MCP_RESULT_DIR"]))
    roots.append(Path(r"D:\aicode\aisystem\results"))
    roots.append(Path.cwd() / "results")
    return roots


def present_cards(name: str, result_text: str, *, roots: list[Path] | None = None) -> list[dict]:
    envelope = _object(result_text)
    if not isinstance(envelope, dict) or envelope.get("ok") is not True:
        return []
    payload = _payload(envelope, roots if roots is not None else result_roots())
    if not isinstance(payload, dict):
        return []
    chart = _chart(payload)
    if chart is not None:
        return [chart]
    table = _table(payload)
    if table is not None:
        return [table]
    return []


def extract_choices(text: str) -> tuple[str, dict | None]:
    match = _FENCE.search(text or "")
    if match is None:
        return text, None
    options = _options(match.group(1))
    cleaned = (text[: match.start()] + text[match.end() :]).strip()
    if not options:
        return text, None
    return cleaned, {"type": "choices", "id": f"cho-{uuid4().hex[:8]}", "options": options, "chosen": None}


def _payload(envelope: dict, roots: list[Path]) -> Any:
    full_file = envelope.get("full_file")
    if not isinstance(full_file, str) or not full_file.strip():
        return None
    return _load(full_file.strip(), roots)


def _load(full_file: str, roots: list[Path]) -> Any:
    raw = Path(full_file)
    candidates = [raw] if raw.is_absolute() else [root / raw for root in roots] + [root.parent / raw for root in roots]
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not _inside(resolved, roots) or not resolved.is_file():
            seen.add(resolved)
            continue
        seen.add(resolved)
        try:
            if resolved.stat().st_size > _FILE_LIMIT:
                return None
            return json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _inside(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            base = root.resolve()
        except OSError:
            continue
        if path == base or base in path.parents:
            return True
    return False


def _table(payload: dict) -> dict | None:
    for key, (title, columns) in _TABLES.items():
        rows = payload.get(key)
        if not isinstance(rows, list) or len(rows) < _TABLE_MIN:
            continue
        kept = [row for row in rows if isinstance(row, dict)][:_ROW_LIMIT]
        if len(kept) < _TABLE_MIN:
            continue
        return {
            "type": "table",
            "id": f"tbl-{uuid4().hex[:8]}",
            "title": title,
            "columns": [label for _, label in columns],
            "rows": [[_cell(row.get(field)) for field, _ in columns] for row in kept],
            "more": max(len(rows) - len(kept), 0),
        }
    return None


def _chart(payload: dict) -> dict | None:
    rows = payload.get("samples")
    if not isinstance(rows, list):
        return None
    points = [row for row in rows if isinstance(row, dict)]
    if len(points) < 2:
        return None
    points = _thin(points, _POINT_LIMIT)
    labels = [_axis(row, index) for index, row in enumerate(points)]
    series = []
    temps = {
        "T0": [_channel(row, "temps", "T0") for row in points],
        "T1": [_channel(row, "temps", "T1") for row in points],
    }
    for name, data in temps.items():
        if any(item is not None for item in data):
            series.append({"type": "line", "name": name, "showSymbol": False, "yAxisIndex": 0, "data": data})
    power = [_number(row.get("power_w"), 3) for row in points]
    if any(item is not None for item in power):
        series.append({"type": "line", "name": "功率", "showSymbol": False, "yAxisIndex": 1, "data": power})
    force = [_channel(row, "forces", "F1") for row in points]
    if any(item is not None for item in force):
        series.append({"type": "line", "name": "压紧力", "showSymbol": False, "yAxisIndex": 2, "data": force})
    if not series:
        return None
    return {
        "type": "chart",
        "id": f"cht-{uuid4().hex[:8]}",
        "title": "采样曲线",
        "option": {
            "tooltip": {"trigger": "axis"},
            "legend": {"top": 0},
            "grid": {"left": 48, "right": 72, "top": 32, "bottom": 28},
            "xAxis": {"type": "category", "data": labels, "name": "s"},
            "yAxis": [
                {"type": "value", "name": "℃"},
                {"type": "value", "name": "W", "position": "right"},
                {"type": "value", "name": "g", "position": "right", "offset": 36},
            ],
            "series": series,
        },
    }


def _options(body: str) -> list[dict]:
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    options = []
    for item in value:
        if not isinstance(item, dict):
            continue
        sentence = " ".join(str(item.get("text") or "").split())
        label = " ".join(str(item.get("label") or "").split())
        if not sentence:
            continue
        options.append({"label": (label or sentence)[:12], "text": sentence[:200]})
        if len(options) == 4:
            break
    return options


def _thin(rows: list[dict], limit: int) -> list[dict]:
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    picked = [rows[min(int(index * step), len(rows) - 1)] for index in range(limit - 1)]
    picked.append(rows[-1])
    return picked


def _axis(row: dict, index: int) -> str:
    value = row.get("t_s")
    if isinstance(value, (int, float)):
        return f"{value:.1f}"
    return str(index + 1)


def _channel(row: dict, key: str, name: str) -> float | None:
    for item in row.get(key) or []:
        if isinstance(item, dict) and item.get("channel") == name:
            return _number(item.get("value"), 2)
    return None


def _number(value: Any, digits: int) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(float(value), digits)


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.3g}"
    if isinstance(value, list):
        shown = "、".join(str(item) for item in value[:4])
        return shown or "—"
    return str(value)[:80]


def _object(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
