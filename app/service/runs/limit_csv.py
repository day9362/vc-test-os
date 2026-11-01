import csv
import io
from typing import Any

IDENTITY = [
    "batch_id",
    "serial_number",
    "batch_count",
    "run_id",
    "machine_id",
    "slot_index",
    "plan_id",
    "plan_version",
    "passed",
    "fail_items",
]


def limit_map(limits: list[dict]) -> dict[str, tuple[Any, Any]]:
    found: dict[str, tuple[Any, Any]] = {}
    for item in limits:
        if not isinstance(item, dict) or item.get("skipped"):
            continue
        name = item.get("item")
        if isinstance(name, str) and name:
            found[name] = (item.get("low", ""), item.get("high", ""))
    return found


def columns_for(limits: dict[str, tuple[Any, Any]]) -> list[str]:
    extra = [name for name in limits if name not in IDENTITY]
    return [*IDENTITY, *extra]


def render_csv(columns: list[str], limits: dict[str, tuple[Any, Any]], rows: list[dict[str, Any]]) -> str:
    upper = ["Upper Limited"]
    lower = ["Lower Limited"]
    for column in columns[1:]:
        low, high = limits.get(column, ("", ""))
        upper.append("" if high is None else high)
        lower.append("" if low is None else low)
    handle = io.StringIO()
    writer = csv.writer(handle)
    writer.writerow(columns)
    writer.writerow(upper)
    writer.writerow(lower)
    for row in rows:
        writer.writerow([row.get(column, "") for column in columns])
    return handle.getvalue()


def channel_value(result: dict, column: str) -> Any:
    if column in result and not isinstance(result.get(column), (dict, list)):
        return result.get(column, "")
    for key in ("temps", "forces", "deltas"):
        for item in result.get(key) or []:
            if isinstance(item, dict) and item.get("channel") == column:
                return item.get("value", "")
    return ""
