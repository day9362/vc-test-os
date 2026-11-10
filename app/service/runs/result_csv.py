"""生产结果表和过程数据表。列名用平台自己的写法，不照搬产线原表。"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

IDENTITY = [
    "model",
    "serial_number",
    "machine_id",
    "slot_index",
    "verdict",
    "fail_items",
    "started_at",
    "ended_at",
    "elapsed_s",
    "planned_duration_s",
    "batch_id",
    "plan_id",
    "plan_version",
]

_TEMP = re.compile(r"^t(\d+)$")
_DELTA = re.compile(r"^t(\d+)-t(\d+)$")
_FORCE = re.compile(r"^f(\d+)$")
_AMBIENT = {"ta", "ambient"}


def export_date() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def build_result_export(rows: list, models: dict[str, str], durations: dict[tuple[str, int], int], group: str) -> tuple[bytes, str, str]:
    if group not in {"day", "batch", "products"}:
        raise ValueError(group)
    built = [_result_row(row, models, durations) for row in rows]
    if group == "products":
        for item in built:
            item.pop("_day", None)
        return _render(built).encode("utf-8-sig"), "text/csv; charset=utf-8", f"products_{export_date()}.csv"
    if group == "batch":
        name = _safe(str(getattr(rows[0], "batch_id", "") or "results")) + ".csv" if rows else "results.csv"
        text = _render(built)
        return text.encode("utf-8-sig"), "text/csv; charset=utf-8", name
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in built:
        buckets.setdefault(str(item.pop("_day")), []).append(item)
    if len(buckets) == 1:
        day, items = next(iter(buckets.items()))
        return _render(items).encode("utf-8-sig"), "text/csv; charset=utf-8", f"{day}.csv"
    if not buckets:
        return _render([]).encode("utf-8-sig"), "text/csv; charset=utf-8", "results.csv"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for day, items in sorted(buckets.items()):
            archive.writestr(f"{day}.csv", _render(items).encode("utf-8-sig"))
    return buffer.getvalue(), "application/zip", "results.zip"


def render_raw(points: list[dict[str, Any]]) -> str:
    columns = ["t_s", *[name for name in _measure_order([set(point) for point in points]) if name != "t_s"]]
    if "t_s" not in columns:
        columns.insert(0, "t_s")
    return _write(columns, points)


def choose_final_sample(samples: list[dict[str, Any]], duration_s: float | None) -> dict[str, Any] | None:
    """取测试方案时长处的采样。时长 180 秒就用 180 秒，时长 10 秒就用 10 秒。"""
    points = [item for item in samples if isinstance(item, dict) and isinstance(item.get("t_s"), (int, float))]
    if not points:
        return None
    if duration_s is None or float(duration_s) <= 0:
        return max(points, key=lambda item: float(item["t_s"]))
    limit = float(duration_s) + 0.05
    within = [item for item in points if float(item["t_s"]) <= limit]
    if within:
        return max(within, key=lambda item: float(item["t_s"]))
    return min(points, key=lambda item: float(item["t_s"]))


def points_from_body(body: object) -> list[dict[str, Any]]:
    items: list = []
    if isinstance(body, dict):
        raw = body.get("samples") or body.get("points") or []
        items = raw if isinstance(raw, list) else []
    elif isinstance(body, list):
        items = body
    points = []
    for item in items:
        if not isinstance(item, dict):
            continue
        point: dict[str, Any] = {"t_s": item.get("t_s", "")}
        point.update(_named_values(item.get("temps")))
        point.update(_named_values(item.get("forces")))
        point.update(_named_values(item.get("deltas")))
        power = item.get("power_w")
        if isinstance(power, (int, float)):
            point["power_w"] = float(power)
        if len(point) > 1:
            points.append(point)
    return points


def raw_filename(batch_id: str, serial: str, ended_at: int, run_id: str) -> str:
    stamp = _clock(ended_at).strftime("%Y%m%d-%H%M%S") if ended_at else "unknown"
    product = serial or run_id or "product"
    return f"{_safe(batch_id or 'batch')}_{_safe(product)}_{stamp}_{export_date()}.csv"


def unique_names(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    used: set[str] = set()
    named = []
    for name, body in pairs:
        candidate = name
        index = 2
        while candidate in used:
            stem, dot, ext = name.rpartition(".")
            candidate = f"{stem}-{index}.{ext}" if dot else f"{name}-{index}"
            index += 1
        used.add(candidate)
        named.append((candidate, body))
    return named


def _result_row(row: Any, models: dict[str, str], durations: dict[tuple[str, int], int]) -> dict[str, Any]:
    result = row.result if isinstance(getattr(row, "result", None), dict) else {}
    planned = durations.get((str(row.plan_id or ""), int(row.plan_version or 0)))
    elapsed = result.get("duration_s") if isinstance(result.get("duration_s"), (int, float)) else planned
    ended = int(row.ended_at or 0)
    started = ended - int(elapsed) * 1000 if ended and isinstance(elapsed, (int, float)) else 0
    verdict = "pass" if row.passed is True else "fail" if row.passed is False else "abort"
    item: dict[str, Any] = {
        "model": models.get(row.batch_id or "", ""),
        "serial_number": row.serial_number or "",
        "machine_id": row.machine_id or "",
        "slot_index": row.slot_index,
        "verdict": verdict,
        "fail_items": ";".join(row.fail_items or []),
        "started_at": _format_ms(started),
        "ended_at": _format_ms(ended),
        "elapsed_s": "" if elapsed is None else elapsed,
        "planned_duration_s": "" if planned is None else planned,
        "batch_id": row.batch_id or "",
        "plan_id": row.plan_id or "",
        "plan_version": row.plan_version,
        "_day": _clock(ended).strftime("%Y-%m-%d") if ended else "unknown",
    }
    item.update(_named_values(result.get("temps")))
    item.update(_named_values(result.get("forces")))
    item.update(_named_values(result.get("deltas")))
    if "delta_t0_t1" not in item and row.dt01 is not None:
        item["delta_t0_t1"] = row.dt01
    if "thermal_resistance" not in item and row.rc is not None:
        item["thermal_resistance"] = row.rc
    power = result.get("power_w")
    if "power_w" not in item and isinstance(power, (int, float)):
        item["power_w"] = float(power)
    return item


def _named_values(raw: object) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for name, value in _pairs(raw):
        header = header_for(name)
        if header and isinstance(value, (int, float)):
            found[header] = float(value)
    return found


def _pairs(raw: object) -> list[tuple[str, object]]:
    if isinstance(raw, dict):
        return [(str(key), value) for key, value in raw.items()]
    if not isinstance(raw, list):
        return []
    pairs = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("channel") or item.get("item") or item.get("name")
        if name:
            pairs.append((str(name), item.get("value")))
    return pairs


def header_for(name: str) -> str | None:
    text = name.strip().lower().replace(" ", "")
    if "60s" in text:
        return None
    if text in {"rc", "thermal_resistance", "temp_rc_t1_ta"}:
        return "thermal_resistance"
    if text in {"power", "power_w", "temp_power"}:
        return "power_w"
    if text in {"dt01", "t0-t1", "temp_t0-t1"}:
        return "delta_t0_t1"
    bare = text
    for prefix in ("temp_", "force_"):
        if bare.startswith(prefix):
            bare = bare[len(prefix):]
    if bare in _AMBIENT:
        return "temp_ambient"
    match = _TEMP.match(bare)
    if match:
        return f"temp_t{int(match.group(1))}"
    match = _DELTA.match(bare)
    if match:
        return f"delta_t{int(match.group(1))}_t{int(match.group(2))}"
    match = _FORCE.match(bare)
    if match:
        return f"force_{int(match.group(1))}"
    return None


def _render(rows: list[dict[str, Any]]) -> str:
    present = [set(row) for row in rows]
    columns = [*IDENTITY, *_measure_order(present)]
    return _write(columns, rows)


def _write(columns: list[str], rows: list[dict[str, Any]]) -> str:
    handle = io.StringIO()
    writer = csv.writer(handle)
    writer.writerow([_label(column) for column in columns])
    for row in rows:
        writer.writerow([_cell(column, row.get(column)) for column in columns])
    return handle.getvalue()


def _label(column: str) -> str:
    unit = _unit(column)
    return f"{column} ({unit})" if unit else column


def _unit(column: str) -> str | None:
    if column in {"t_s", "elapsed_s", "planned_duration_s"}:
        return "s"
    if column.startswith("temp_") or column.startswith("delta_"):
        return "℃"
    if column.startswith("force_"):
        return "g"
    if column == "power_w":
        return "W"
    if column == "thermal_resistance":
        return "℃/W"
    return None


def _cell(column: str, value: object) -> object:
    if value is None:
        return ""
    if _unit(column) and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.2f}"
    return value


def _measure_order(present: list[set[str]]) -> list[str]:
    names = {name for keys in present for name in keys if name not in IDENTITY and not name.startswith("_")}
    return sorted(names, key=_measure_key)


def _measure_key(header: str) -> tuple:
    if header.startswith("temp_t") and header.removeprefix("temp_t").isdigit():
        return (0, int(header.removeprefix("temp_t")), 0, 0)
    if header == "temp_ambient":
        return (1, 0, 0, 0)
    if header.startswith("delta_t"):
        parts = header.removeprefix("delta_").split("_")
        nums = [int(part[1:]) for part in parts if part.startswith("t") and part[1:].isdigit()]
        if len(nums) == 2:
            return (2, 0 if nums == [0, 1] else 1, nums[0], nums[1])
    if header.startswith("force_") and header.removeprefix("force_").isdigit():
        return (3, int(header.removeprefix("force_")), 0, 0)
    if header == "power_w":
        return (4, 0, 0, 0)
    if header == "thermal_resistance":
        return (5, 0, 0, 0)
    return (9, header, 0, 0)


def _format_ms(value: int) -> str:
    if not value:
        return ""
    return _clock(value).strftime("%Y-%m-%d %H:%M:%S")


def _clock(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, TZ)


def _safe(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "item"
