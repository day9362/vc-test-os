"""卡限项的重复性、相关性和偏移。过程曲线上的点不算重复测量。"""

from __future__ import annotations

import re
from math import sqrt
from typing import Any

_INVALID = {99999.0, 9999.0, -1.0, -2.0}
_SAMPLE = {
    "temp_t0": ("t0",),
    "temp_t1": ("t1",),
    "temp_ambient": ("ta",),
    "power_w": ("power_w",),
    "delta_t0_t1": ("t0", "t1"),
}


def item_sort_key(name: str) -> tuple:
    bare = name[5:] if name.lower().startswith("temp_") else name
    delta = re.match(r"^T(\d+)-T(\d+)$", bare, re.I)
    if delta:
        return (0, int(delta.group(1)), int(delta.group(2)), name)
    point = re.match(r"^T(\d+)$", bare, re.I)
    if point:
        return (0, int(point.group(1)), -1, name)
    if name == "power_w":
        return (4, 0, 0, name)
    return (9, 0, 0, name)


def usable(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return float(value) not in _INVALID


def summarize(item: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["value"]) for row in rows]
    count = len(values)
    low, high = _common_limit(rows)
    mean = _mean(values)
    std = _std(values)
    minimum = min(values) if values else None
    maximum = max(values) if values else None
    high_fail = sum(1 for row in rows if row["high"] is not None and row["value"] > row["high"])
    low_fail = sum(1 for row in rows if row["low"] is not None and row["value"] < row["low"])
    return {
        "item": item,
        "n": count,
        "mean": _round(mean),
        "minimum": _round(minimum),
        "maximum": _round(maximum),
        "range": _round(None if minimum is None or maximum is None else maximum - minimum),
        "std": _round(std),
        "low": _round(low),
        "high": _round(high),
        "high_fail": high_fail,
        "low_fail": low_fail,
        "offset": _offset(rows),
        "margin_high": _round(_margin_high(rows)),
        "margin_low": _round(_margin_low(rows)),
        "cpk": _round(_cpk(values, low, high, std)),
        "repeat_std": _round(std),
        "retest_serials": _retests(rows)[0],
        "retest_range": _round(_retests(rows)[1]),
        "trend": _trend(rows),
        "invalid": sum(int(row.get("invalid") or 0) for row in rows),
    }


def correlate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_run: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_run.setdefault(row["run_id"], {})[row["item"]] = row
    names = sorted({row["item"] for row in rows})
    pairs = []
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            matched = []
            co_fail = 0
            for items in by_run.values():
                if left not in items or right not in items:
                    continue
                matched.append((float(items[left]["value"]), float(items[right]["value"])))
                if _failed(items[left]) and _failed(items[right]):
                    co_fail += 1
            score = _pearson(matched)
            if score is None and co_fail == 0:
                continue
            pairs.append({
                "left": left,
                "right": right,
                "r": _round(score),
                "n": len(matched),
                "co_fail": co_fail,
            })
    pairs.sort(key=lambda item: abs(item["r"] or 0), reverse=True)
    return pairs[:8]


def process_shape(points: list[float], low: float | None, high: float | None) -> str:
    values = [float(item) for item in points if usable(item)]
    if len(values) < 4 or (low is None and high is None):
        return ""
    flags = [_outside(value, low, high) for value in values]
    if not any(flags):
        return "过程未超上限、未超下限"
    head = max(int(len(flags) * 0.8), 1)
    side = _process_side(values, flags, low, high)
    if sum(flags) / len(flags) >= 0.5:
        return f"全程{side}"
    if any(flags[head:]) and not any(flags[:head]):
        return f"结束前{side}"
    return f"中途{side}"


def sample_series(item_key: str, points: list[dict[str, Any]]) -> list[float]:
    fields = _SAMPLE.get(item_key)
    if not fields:
        return []
    ordered = sorted(points, key=lambda item: float(item.get("t_s") or 0))
    values = []
    for point in ordered:
        if len(fields) == 1:
            raw = point.get(fields[0])
            if usable(raw):
                values.append(float(raw))
        else:
            left, right = point.get(fields[0]), point.get(fields[1])
            if usable(left) and usable(right):
                values.append(float(left) - float(right))
    return values


def _process_side(values: list[float], flags: list[bool], low: float | None, high: float | None) -> str:
    high_side = any(flag and high is not None and value > high for value, flag in zip(values, flags))
    low_side = any(flag and low is not None and value < low for value, flag in zip(values, flags))
    if high_side and low_side:
        return "超上限或超下限"
    if low_side:
        return "超下限"
    return "超上限"


def fail_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_run: dict[str, set[str]] = {}
    for row in rows:
        found = by_run.setdefault(str(row["run_id"]), set())
        if _failed(row):
            found.add(str(row["item"]))
    counts: dict[tuple[str, ...], int] = {}
    for items in by_run.values():
        if not items:
            continue
        key = tuple(sorted(items, key=item_sort_key))
        counts[key] = counts.get(key, 0) + 1
    groups = [{"items": list(key), "count": count} for key, count in counts.items()]
    groups.sort(key=lambda group: (len(group["items"]) != 1, -group["count"], item_sort_key(group["items"][0])))
    return groups


def _failed(row: dict[str, Any]) -> bool:
    return (row["high"] is not None and row["value"] > row["high"]) or (row["low"] is not None and row["value"] < row["low"])


def _outside(value: float, low: float | None, high: float | None) -> bool:
    return (high is not None and value > high) or (low is not None and value < low)


def _common_limit(rows: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    lows = {row["low"] for row in rows}
    highs = {row["high"] for row in rows}
    low = next(iter(lows)) if len(lows) == 1 else None
    high = next(iter(highs)) if len(highs) == 1 else None
    return low, high


def _offset(rows: list[dict[str, Any]]) -> str:
    positions = []
    for row in rows:
        low, high = row["low"], row["high"]
        if low is None or high is None or high <= low:
            continue
        positions.append((float(row["value"]) - low) / (high - low))
    if not positions:
        return "单侧限"
    mean = sum(positions) / len(positions)
    if mean < 0.35:
        return "偏下限"
    if mean > 0.65:
        return "偏上限"
    return "居中"


def _margin_high(rows: list[dict[str, Any]]) -> float | None:
    rooms = [row["high"] - row["value"] for row in rows if row["high"] is not None and not _failed(row)]
    return min(rooms) if rooms else None


def _margin_low(rows: list[dict[str, Any]]) -> float | None:
    rooms = [row["value"] - row["low"] for row in rows if row["low"] is not None and not _failed(row)]
    return min(rooms) if rooms else None


def _cpk(values: list[float], low: float | None, high: float | None, std: float | None) -> float | None:
    if len(values) < 20 or not std:
        return None
    mean = _mean(values)
    sides = []
    if high is not None:
        sides.append((high - mean) / (3 * std))
    if low is not None:
        sides.append((mean - low) / (3 * std))
    return min(sides) if sides else None


def _retests(rows: list[dict[str, Any]]) -> tuple[int, float | None]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        serial = str(row.get("serial") or "")
        if serial:
            grouped.setdefault(serial, []).append(float(row["value"]))
    ranges = [max(values) - min(values) for values in grouped.values() if len(values) >= 2]
    if not ranges:
        return 0, None
    return len(ranges), sum(ranges) / len(ranges)


def _trend(rows: list[dict[str, Any]]) -> str:
    ordered = sorted(rows, key=lambda row: int(row.get("ended_at") or 0))
    if len(ordered) < 4:
        return "片数不足"
    mid = len(ordered) // 2
    first = _mean([float(row["value"]) for row in ordered[:mid]])
    second = _mean([float(row["value"]) for row in ordered[mid:]])
    if abs(second - first) <= max(0.02, 0.05 * abs(first)):
        return "持平"
    return "后半段升高" if second > first else "后半段降低"


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    count = len(pairs)
    if count < 5:
        return None
    xs = [item[0] for item in pairs]
    ys = [item[1] for item in pairs]
    mean_x, mean_y = _mean(xs), _mean(ys)
    var_x = sum((item - mean_x) ** 2 for item in xs)
    var_y = sum((item - mean_y) ** 2 for item in ys)
    if var_x == 0 or var_y == 0:
        return None
    cov = sum((item[0] - mean_x) * (item[1] - mean_y) for item in pairs)
    return cov / sqrt(var_x * var_y)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = _mean(values)
    return sqrt(sum((item - mean) ** 2 for item in values) / (len(values) - 1))


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)
