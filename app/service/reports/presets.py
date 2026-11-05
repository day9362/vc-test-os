import re
import statistics
from collections import defaultdict

from app.core.errors import AppError
from app.service.reports.analysis_math import item_sort_key
from app.service.reports.stats import five_number, welch

_PLACE = re.compile(r"M(\d+)|槽(\d+)", re.I)


class Preset:
    def __init__(self, preset_id: str, label: str):
        self.id = preset_id
        self.label = label


PRESETS = {
    item.id: item
    for item in (
        Preset("slot_rc", "槽位箱线"),
        Preset("scatter", "分项分布"),
        Preset("pareto", "超限片数"),
        Preset("trend", "温差走势"),
        Preset("heatmap", "机台×槽位"),
        Preset("compare", "同项对比"),
    )
}


_DELTA = re.compile(r"^Temp_T\d+-T\d+$", re.I)


def run_preset(preset_id: str, records: list[dict], group: str = "", show_ambient: bool = False) -> dict:
    if preset_id == "grouped":
        return _grouped(records, group or "slot", show_ambient)
    if preset_id == "machine_batch":
        return _machine_then_batch(records, show_ambient)
    if preset_id == "overview":
        return _overview(records, show_ambient)
    builder = {
        "overview": _overview,
        "slot_rc": _slot_boxes,
        "scatter": _distribution,
        "pareto": _over_counts,
        "trend": _trend,
        "heatmap": _heatmap,
        "compare": _compare,
    }.get(preset_id)
    if builder is None or (preset_id != "overview" and preset_id not in PRESETS):
        raise AppError(400, "BAD_REQUEST", "没有这种分析")
    return builder(records)


def fail_names(value: object) -> list[str]:
    if isinstance(value, list):
        parts = [str(item).strip() for item in value]
    elif isinstance(value, str):
        parts = [item.strip() for item in value.split("、")]
    else:
        return []
    return [item for item in parts if item]


def test_rows(records: list[dict], tests: object) -> list[list[str]]:
    if not isinstance(tests, list):
        return []
    rows: list[list[str]] = []
    for item in tests[:3]:
        if not isinstance(item, dict):
            continue
        rows.extend(_one_test(records, item))
    return rows


def _grouped(records: list[dict], group: str, show_ambient: bool = False) -> dict:
    axis = {"slot": "槽位", "machine": "机台", "batch": "批次"}.get(group, "槽位")
    return _done(f"按{axis}的卡限项", _group_panels(records, group, show_ambient))


def _machine_then_batch(records: list[dict], show_ambient: bool = False) -> dict:
    names = _item_names(records, limited_only=True)
    batches = _batch_order(records)
    machine = {panel["title"]: panel for panel in _group_panels(records, "machine", False)}
    batch = {panel["title"]: panel for panel in _group_panels(records, "batch", False)}
    chosen = [name for name in names if name in machine or name in batch][:8]
    panels = []
    for name in chosen:
        if len(batches) >= 2:
            panel = _machine_batches(records, name, batches)
            if panel:
                panels.append(panel)
        elif name in machine:
            panels.append(_retitle(machine[name], f"{name}（机台）"))
    panels += [_retitle(batch[name], f"{name}（批次）") for name in chosen if name in batch]
    if show_ambient:
        ambient = _ambient_panel(records)
        if ambient:
            panels.append(ambient)
    return _done("按机台、按批次的卡限项", panels)


def _group_panels(records: list[dict], group: str, show_ambient: bool) -> list[dict]:
    axis = {"slot": "槽位", "machine": "机台", "batch": "批次"}.get(group, "槽位")
    panels = []
    names = [name for name in _item_names(records, limited_only=True) if show_ambient or name != "室温"]
    for name in names:
        grouped: dict[str, list[float]] = defaultdict(list)
        chosen = []
        for point in _chart_points(records):
            if point["item"] != name:
                continue
            label = _group_label(point, group)
            if not label:
                continue
            grouped[label].append(point["value"])
            chosen.append(point)
        if not grouped:
            continue
        labels = sorted(grouped, key=_place_key)
        panel = _box(name, axis, labels, [grouped[label] for label in labels], chosen)
        panel["y_name"] = "W" if name == "power_w" else "℃"
        panels.append(panel)
    return panels


def _retitle(panel: dict, title: str) -> dict:
    copied = dict(panel)
    copied["title"] = title
    return copied


def _batch_order(records: list[dict]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for point in _chart_points(records):
        batch = point["batch_id"]
        if batch and batch not in seen:
            seen.add(batch)
            ordered.append(batch)
    return ordered


def _machine_batches(records: list[dict], name: str, batches: list[str]) -> dict | None:
    points = [point for point in _chart_points(records) if point["item"] == name and point["machine_id"]]
    if not points:
        return None
    machines = sorted({point["machine_id"] for point in points}, key=_place_key)[:24]
    shown = batches[:6]
    series = []
    for batch in shown:
        rows: list[list[float] | None] = []
        for machine in machines:
            values = [point["value"] for point in points if point["batch_id"] == batch and point["machine_id"] == machine]
            rows.append(five_number(values) if values else None)
        series.append({"name": batch, "data": rows})
    return {
        "title": f"{name}（机台）",
        "type": "boxplot",
        "x_name": "机台",
        "y_name": "W" if name == "power_w" else "℃",
        "categories": machines,
        "series": series,
        "marks": _limit_marks(points),
    }


def _group_label(point: dict, group: str) -> str:
    if group == "batch":
        return str(point.get("batch_id") or "")
    if group == "machine":
        return str(point.get("machine_id") or "")
    return _place(point)


def _overview(records: list[dict], show_ambient: bool = False) -> dict:
    panels = _distribution(records)["panels"]
    counts = _over_bar(records)
    if counts:
        panels.append(counts)
    panels.extend(_slot_mean_bars(records))
    if show_ambient:
        ambient = _ambient_panel(records)
        if ambient:
            panels.append(ambient)
    if not panels:
        raise AppError(400, "BAD_REQUEST", "这些批次没有可画的温差")
    return {"title": "温差", "panels": panels, "results": []}


def _slot_boxes(records: list[dict]) -> dict:
    panels = []
    for name in _item_names(records, delta_only=True):
        chosen = [point for point in _chart_points(records) if point["item"] == name]
        grouped: dict[str, list[float]] = defaultdict(list)
        for point in chosen:
            place = _place(point)
            if place:
                grouped[place].append(point["value"])
        if not grouped:
            grouped["本批"] = [point["value"] for point in chosen]
        labels = sorted(grouped, key=_place_key)
        panels.append(_box(name, "槽位", labels, [grouped[label] for label in labels], chosen))
    return _done("按槽位的温差", panels)


def _distribution(records: list[dict]) -> dict:
    names = _item_names(records, delta_only=True)
    grouped = {name: [point["value"] for point in _chart_points(records) if point["item"] == name] for name in names}
    chosen = [point for point in _chart_points(records) if point["item"] in grouped]
    panel = _box("温差分布", "项", names, [grouped[name] for name in names], chosen)
    return _done("温差分布", [panel])


def _over_counts(records: list[dict]) -> dict:
    panel = _over_bar(records)
    if panel is None:
        raise AppError(400, "BAD_REQUEST", "这些批次没有卡限温差")
    return _done("超限片数", [panel])


def _trend(records: list[dict]) -> dict:
    panels = []
    for name in _item_names(records, limited_only=True, delta_only=True):
        chosen = [point for point in _chart_points(records) if point["item"] == name]
        chosen.sort(key=lambda point: point["ended_at"] or 0)
        if len(chosen) < 2:
            continue
        labels = [f"第{index}片" for index, _ in enumerate(chosen, start=1)]
        panels.append({
            "title": name,
            "type": "line",
            "x_name": "测试顺序",
            "y_name": "℃",
            "categories": labels,
            "series": [{"name": name, "data": [round(point["value"], 3) for point in chosen]}],
            "marks": _limit_marks(chosen),
        })
    return _done("温差走势", panels)


def _heatmap(records: list[dict]) -> dict:
    names = _item_names(records, limited_only=True, delta_only=True)
    if not names:
        raise AppError(400, "BAD_REQUEST", "这些批次没有卡限温差")
    panels = []
    for item in names:
        panel = _one_heatmap(records, item)
        if panel:
            panels.append(panel)
    if not panels:
        raise AppError(400, "BAD_REQUEST", "没有机台或槽位")
    return {"title": "机台与槽位", "panels": panels, "results": []}


def _one_heatmap(records: list[dict], item: str) -> dict | None:
    chosen = [point for point in _chart_points(records) if point["item"] == item and point["machine_id"] and _slot_number(point) is not None]
    if not chosen:
        return None
    grouped: dict[tuple[str, int], list[float]] = defaultdict(list)
    for point in chosen:
        grouped[(point["machine_id"], _slot_number(point))].append(point["value"])
    machines = sorted({machine for machine, _ in grouped})[:12]
    slots = sorted({slot for _, slot in grouped})[:16]
    cells = []
    for y_index, machine in enumerate(machines):
        for x_index, slot in enumerate(slots):
            values = grouped.get((machine, slot))
            if values:
                cells.append([x_index, y_index, round(statistics.fmean(values), 3)])
    if not cells:
        return None
    return {
        "title": item,
        "type": "heatmap",
        "x_name": "槽位",
        "y_name": item,
        "x_labels": [f"槽{slot}" for slot in slots],
        "y_labels": machines,
        "data": cells,
    }


def _compare(records: list[dict]) -> dict:
    points = _chart_points(records)
    batches = {point["batch_id"] for point in points if point["batch_id"]}
    places = {_place(point) for point in points if _place(point)}
    panels = []
    for name in _item_names(records, delta_only=True):
        chosen = [point for point in points if point["item"] == name]
        grouped: dict[str, list[float]] = defaultdict(list)
        for point in chosen:
            if len(batches) > 1:
                label, axis = point["batch_id"], "批次"
            elif len(places) > 1:
                label, axis = _place(point), "槽位"
            else:
                label, axis = point["machine_id"] or "本批", "机台"
            if label:
                grouped[label].append(point["value"])
        labels = sorted(grouped, key=_place_key)
        panels.append(_box(name, axis, labels, [grouped[label] for label in labels], chosen))
    return _done("同项对比", panels)


def _ambient_panel(records: list[dict]) -> dict | None:
    grouped: dict[str, list[float]] = defaultdict(list)
    for record in records:
        value = record.get("ambient")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        machine = str(record.get("machine_id") or "")
        slot = record.get("slot_index")
        if machine and isinstance(slot, int) and not isinstance(slot, bool):
            label = f"{machine} 槽{slot}"
        else:
            label = "本批"
        grouped[label].append(float(value))
    if not grouped:
        return None
    labels = sorted(grouped, key=_place_key)
    if len(labels) == 1 and len(grouped[labels[0]]) >= 2:
        values = grouped[labels[0]]
        return {
            "title": "室温",
            "type": "line",
            "x_name": "测试顺序",
            "y_name": "℃",
            "categories": [f"第{index}片" for index in range(1, len(values) + 1)],
            "series": [{"name": "室温", "data": [round(value, 3) for value in values]}],
        }
    return _box("室温", "槽位", labels, [grouped[label] for label in labels], [])


def _done(title: str, panels: list[dict]) -> dict:
    if not panels:
        raise AppError(400, "BAD_REQUEST", "这些批次没有可画的温差")
    return {"title": title, "panels": panels, "results": []}


def _box(title: str, x_name: str, labels: list[str], groups: list[list[float]], chosen: list[dict]) -> dict:
    return {
        "title": title,
        "type": "boxplot",
        "x_name": x_name,
        "y_name": "℃",
        "categories": labels,
        "series": [{"name": title, "data": [five_number(values) for values in groups]}],
        "marks": _limit_marks(chosen),
    }


def _over_bar(records: list[dict]) -> dict | None:
    names = _item_names(records, limited_only=True, delta_only=True)
    if not names:
        return None
    highs = []
    lows = []
    for name in names:
        chosen = [point for point in _chart_points(records) if point["item"] == name and point["limited"]]
        highs.append(sum(1 for point in chosen if _above(point)))
        lows.append(sum(1 for point in chosen if _below(point)))
    return {
        "title": "超限片数",
        "type": "bar",
        "x_name": "项",
        "y_name": "片",
        "categories": names,
        "series": [{"name": "超上限", "data": highs}, {"name": "超下限", "data": lows}],
    }


def _slot_mean_bars(records: list[dict]) -> list[dict]:
    panels = []
    for name in _item_names(records, limited_only=True, delta_only=True):
        panel = _slot_mean_bar(records, name)
        if panel:
            panels.append(panel)
    return panels


def _slot_mean_bar(records: list[dict], name: str) -> dict | None:
    grouped: dict[str, list[float]] = defaultdict(list)
    chosen = []
    for point in _chart_points(records):
        if point["item"] != name:
            continue
        place = _place(point)
        if not place:
            continue
        chosen.append(point)
        grouped[place].append(point["value"])
    if len(grouped) < 2:
        return None
    labels = sorted(grouped, key=_place_key)
    return {
        "title": f"{name} 槽位均值",
        "type": "bar",
        "x_name": "槽位",
        "y_name": "℃",
        "categories": labels,
        "series": [{"name": name, "data": [round(statistics.fmean(grouped[label]), 3) for label in labels]}],
        "marks": _limit_marks(chosen),
    }


def _is_delta(name: str) -> bool:
    return bool(_DELTA.match(name))


def _item_names(records: list[dict], *, limited_only: bool = False, delta_only: bool = False) -> list[str]:
    rank: dict[str, tuple] = {}
    for point in _chart_points(records):
        if limited_only and not point["limited"]:
            continue
        if delta_only and not _is_delta(point["item"]):
            continue
        order = point.get("order")
        key = (order if isinstance(order, int) else 10**9, item_sort_key(point["item"]))
        current = rank.get(point["item"])
        if current is None or key < current:
            rank[point["item"]] = key
    return sorted(rank, key=lambda name: rank[name])


def _chart_points(records: list[dict]) -> list[dict]:
    points = []
    for record in records:
        for item in _delta_list(record):
            value = _finite(item.get("value"))
            name = str(item.get("item") or "").strip()
            if value is None or not name:
                continue
            low = _finite(item.get("low"))
            high = _finite(item.get("high"))
            limited = item.get("limited") is not False and (low is not None or high is not None)
            ended = record.get("ended_at")
            order = item.get("order")
            points.append({
                "item": name,
                "order": order if isinstance(order, int) and not isinstance(order, bool) else None,
                "value": value,
                "low": low,
                "high": high,
                "limited": limited,
                "batch_id": str(record.get("batch_id") or ""),
                "machine_id": str(record.get("machine_id") or ""),
                "slot_index": record.get("slot_index"),
                "ended_at": ended if isinstance(ended, int) and not isinstance(ended, bool) else 0,
            })
    return points


def _place(point: dict) -> str:
    slot = _slot_number(point)
    if slot is None:
        return ""
    machine = point["machine_id"]
    return f"{machine} 槽{slot}" if machine else f"槽{slot}"


def _slot_number(point: dict) -> int | None:
    slot = point.get("slot_index")
    if isinstance(slot, bool) or not isinstance(slot, int):
        return None
    return slot


def _place_key(label: str) -> tuple:
    machine = 0
    slot = 0
    for kind, number in _PLACE.findall(label):
        if kind:
            machine = int(kind)
        if number:
            slot = int(number)
    return (machine, slot, label)


def _above(point: dict) -> bool:
    high = _finite(point.get("high"))
    return high is not None and point["value"] > high


def _below(point: dict) -> bool:
    low = _finite(point.get("low"))
    return low is not None and point["value"] < low


def _one_test(records: list[dict], spec: dict) -> list[list[str]]:
    measure = str(spec.get("y") or "").strip()
    group = str(spec.get("by") or "")
    if not measure or group not in {"batch_id", "machine_id", "slot_index", "passed"}:
        return []
    left_name = str(spec.get("left") or "").strip()
    right_name = str(spec.get("right") or "").strip()
    if not left_name or not right_name:
        return []
    grouped = _delta_groups(records, group, measure)
    left = grouped.get(_canon(group, left_name))
    right = grouped.get(_canon(group, right_name))
    if left is None or right is None:
        return [[f"{left_name} 与 {right_name}", "没有这两组数据"]]
    compared = welch(left, right)
    if compared is None:
        return [[f"{left_name} 与 {right_name}", "样本不足"]]
    return [
        [f"{measure} {left_name} 均值", _mean_text(left)],
        [f"{measure} {right_name} 均值", _mean_text(right)],
        [f"{left_name} − {right_name}", _fmt(compared["diff"])],
        ["Welch t p 值", _fmt_p(compared["p"])],
    ]


def _delta_points(records: list[dict]) -> list[dict]:
    points = []
    for record in records:
        for item in _delta_list(record):
            value = _finite(item.get("value"))
            if value is None or not str(item.get("item") or "").strip() or item.get("limited") is False:
                continue
            points.append({
                "item": str(item["item"]),
                "value": value,
                "low": item.get("low"),
                "high": item.get("high"),
                "batch_id": str(record.get("batch_id") or ""),
                "machine_id": str(record.get("machine_id") or ""),
                "slot_index": record.get("slot_index"),
                "ended_at": record.get("ended_at"),
                "passed": record.get("passed"),
            })
    return points


def _delta_list(record: dict) -> list[dict]:
    raw = record.get("deltas")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _limit_marks(points: list[dict]) -> list[dict]:
    marks = []
    high = _one_limit(point.get("high") for point in points)
    low = _one_limit(point.get("low") for point in points)
    if high is not None:
        marks.append({"name": "上限", "y": high})
    if low not in {None, 0}:
        marks.append({"name": "下限", "y": low})
    return marks


def _one_limit(values) -> float | None:
    found: list[float] = []
    for value in values:
        number = _finite(value)
        if number is not None and number not in found:
            found.append(number)
    if len(found) == 1:
        return found[0]
    return None


def _delta_groups(records: list[dict], key: str, measure: str) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for point in _delta_points(records):
        if point["item"] != measure:
            continue
        grouped[_canon(key, point.get(key))].append(point["value"])
    return dict(grouped)


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in {float("inf"), float("-inf")}:
        return None
    return float(value)


def _canon(key: str, value: object) -> str:
    if key == "passed":
        return _pass_name(value if not isinstance(value, str) else _passed_text(value))
    return str(value if value is not None else "").strip()


def _passed_text(value: str) -> bool | None:
    folded = value.strip().lower()
    if folded in {"true", "1", "合格", "passed"}:
        return True
    if folded in {"false", "0", "不合格", "failed"}:
        return False
    return None


def _pass_name(value: object) -> str:
    if value is True:
        return "合格"
    if value is False:
        return "不合格"
    return "未判定"


def _mean_text(values: list[float]) -> str:
    return f"{_fmt(statistics.fmean(values))}（n={len(values)}）"


def _fmt(value: float) -> str:
    return f"{value:.4g}"


def _fmt_p(value: float) -> str:
    if value < 0.001:
        return "<0.001"
    return f"{value:.3f}"
