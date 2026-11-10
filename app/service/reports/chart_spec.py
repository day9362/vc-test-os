import re

from app.core.errors import AppError
from app.service.reports.sandbox import sanitize_option

_TYPES = {"boxplot", "scatter", "bar", "line", "heatmap", "pareto", "spindle"}
_MAX_PANELS = 16
_MAX_CATEGORIES = 24
_MAX_SERIES = 6
_MAX_POINTS = 800
_MAX_CELLS = 400


def compile_stored(result: dict) -> tuple[list[dict], str]:
    raw = result.get("panels")
    if raw is not None:
        panels, error = _compile_panels(raw)
        if panels:
            return panels, ""
        if error:
            return [], error
    option = result.get("echarts_option")
    if option:
        try:
            cleaned = sanitize_option(option)
        except AppError as exc:
            return [], exc.message
        if cleaned:
            return [{"title": "", "option": cleaned}], ""
    return [], ""


def panels_from_stored(stored: object) -> list[dict]:
    if not isinstance(stored, dict):
        return []
    raw = stored.get("panels")
    if isinstance(raw, list) and raw and all(_is_panel(item) for item in raw):
        return [{"title": str(item.get("title") or "")[:40], "option": _fit_stored(item["option"])} for item in raw[:_MAX_PANELS]]
    if stored.get("series") is not None or stored.get("xAxis") is not None or stored.get("dataset") is not None:
        return [{"title": "", "option": stored}]
    return []


def _compile_panels(raw: object) -> tuple[list[dict], str]:
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        return [], "panels 需要是图表说明的列表"
    panels: list[dict] = []
    first_error = ""
    for item in raw[:_MAX_PANELS]:
        if not isinstance(item, dict):
            first_error = first_error or "图表说明不是对象"
            continue
        try:
            option = compile_panel(item)
        except AppError as exc:
            first_error = first_error or exc.message
            continue
        panels.append({"title": _text(item.get("title"), 40), "option": option})
    if panels:
        return panels, ""
    return [], first_error or "图表说明没有可画的数据"


def compile_panel(spec: dict) -> dict:
    kind = str(spec.get("type") or "").strip().lower()
    if kind not in _TYPES:
        raise AppError(502, "AGENT_FAILED", "图表类型只能是 boxplot、scatter、bar、line、heatmap、pareto、spindle")
    if kind == "heatmap":
        option = _heatmap(spec)
    elif kind == "scatter":
        option = _scatter(spec)
    elif kind == "pareto":
        option = _pareto(spec)
    elif kind == "boxplot":
        option = _boxes(spec)
    elif kind == "spindle":
        option = _spindle(spec)
    else:
        option = _categories(spec, kind)
    option["tip"] = _tip(spec, kind)
    return option


def _boxes(spec: dict) -> dict:
    categories = _categories_of(spec)
    series = []
    for item in _series_of(spec):
        rows = []
        for raw in item["data"][: len(categories)]:
            parsed = _box_row(raw)
            rows.append("-" if parsed is None else parsed)
        if len(rows) != len(categories):
            continue
        series.append({"type": "boxplot", "name": item["name"], "data": rows})
    if not categories or not series:
        raise AppError(502, "AGENT_FAILED", "箱线图缺少分组数据")
    option = _axes(spec, categories, series)
    _marks(option, spec)
    return option


def _spindle(spec: dict) -> dict:
    categories = _categories_of(spec)
    series = []
    for item in _series_of(spec):
        rows = []
        for raw in item["data"][: len(categories)]:
            parsed = _spindle_row(raw)
            if parsed is None:
                rows = []
                break
            rows.append(parsed)
        if len(rows) != len(categories):
            continue
        series.append({"type": "candlestick", "name": item["name"], "data": rows})
    if not categories or not series:
        raise AppError(502, "AGENT_FAILED", "纺锤图缺少最小、均值、最大")
    option = _axes(spec, categories, series)
    _marks(option, spec)
    return option


def _spindle_row(raw: object) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) < 3:
        return None
    low, mean, high = (_finite(raw[0]), _finite(raw[1]), _finite(raw[2]))
    if low is None or mean is None or high is None:
        return None
    return [_shown(mean), _shown(mean), _shown(low), _shown(high)]


def _categories(spec: dict, kind: str) -> dict:
    categories = _categories_of(spec)
    series = []
    for item in _series_of(spec):
        values = [_shown(number) if (number := _finite(raw)) is not None else None for raw in item["data"][: len(categories)]]
        if len(values) != len(categories) or any(value is None for value in values):
            continue
        series.append({"type": kind, "name": item["name"], "data": values})
    if not categories or not series:
        raise AppError(502, "AGENT_FAILED", "分类图缺少数据")
    option = _axes(spec, categories, series)
    if len(categories) > 8 and kind in {"bar", "line"}:
        option = {
            "yAxis": {"type": "category", "data": categories, "name": _text(spec.get("x_name"), 20)},
            "xAxis": {"type": "value", "name": _text(spec.get("y_name"), 20), "scale": True},
            "series": series,
        }
        _marks(option, spec, "xAxis")
        return option
    _marks(option, spec)
    return option


def _pareto(spec: dict) -> dict:
    pairs: list[tuple[str, float]] = []
    categories = _categories_of(spec)
    series = _series_of(spec)
    if categories and series:
        for index, label in enumerate(categories):
            value = _finite(series[0]["data"][index]) if index < len(series[0]["data"]) else None
            if value is None or value < 0:
                continue
            pairs.append((label, value))
    pairs.sort(key=lambda item: item[1], reverse=True)
    pairs = pairs[:_MAX_CATEGORIES]
    total = sum(value for _, value in pairs)
    if not pairs or total <= 0:
        raise AppError(502, "AGENT_FAILED", "帕累托图缺少次数")
    running = 0.0
    cumulative = []
    for _, value in pairs:
        running += value
        cumulative.append(round(100 * running / total, 1))
    option = {
        "xAxis": {"type": "category", "data": [label for label, _ in pairs], "name": _text(spec.get("x_name"), 20)},
        "yAxis": [
            {"type": "value", "name": _text(spec.get("y_name"), 20) or "次数"},
            {"type": "value", "name": "累计 %", "min": 0, "max": 100},
        ],
        "series": [
            {"type": "bar", "name": "次数", "unit": "片", "role": "片数", "data": [value for _, value in pairs]},
            {"type": "line", "name": "累计", "unit": "%", "role": "累计", "yAxisIndex": 1, "data": cumulative},
        ],
    }
    return option


def _scatter(spec: dict) -> dict:
    series = []
    for item in _series_of(spec):
        points = []
        for raw in item["data"]:
            point = _point(raw)
            if point is not None:
                points.append(point)
        points = _thin(points, _MAX_POINTS)
        if points:
            series.append({"type": "scatter", "name": item["name"], "data": points})
    if not series:
        raise AppError(502, "AGENT_FAILED", "散点图缺少坐标")
    return _slot_axis({
        "xAxis": {"type": "value", "name": _text(spec.get("x_name"), 20), "scale": True},
        "yAxis": {"type": "value", "name": _text(spec.get("y_name"), 20), "scale": True},
        "series": series,
    })


def _heatmap(spec: dict) -> dict:
    x_labels = [_text(item, 24) for item in _label_list(spec.get("x_labels"))][:_MAX_CATEGORIES]
    y_labels = [_text(item, 24) for item in _label_list(spec.get("y_labels"))][:_MAX_CATEGORIES]
    cells = []
    raw_cells = spec.get("data")
    if not isinstance(raw_cells, list):
        series = _series_of(spec)
        raw_cells = series[0]["data"] if series else []
    for raw in raw_cells:
        cell = _cell(raw, len(x_labels), len(y_labels))
        if cell is not None:
            cells.append(cell)
        if len(cells) >= _MAX_CELLS:
            break
    if not x_labels or not y_labels or not cells:
        raise AppError(502, "AGENT_FAILED", "热力图缺少格子")
    values = [item[2] for item in cells]
    low = min(values)
    high = max(values)
    if low == high:
        high = low + 1
    return {
        "grid": {"left": 8, "right": 16, "top": 24, "bottom": 36, "containLabel": True},
        "xAxis": {"type": "category", "data": x_labels, "name": _text(spec.get("x_name"), 20)},
        "yAxis": {"type": "category", "data": y_labels, "name": _text(spec.get("y_name"), 20)},
        "visualMap": {"min": low, "max": high, "calculable": False, "orient": "horizontal", "left": "center", "bottom": 0},
        "series": [{"type": "heatmap", "data": cells, "name": _text(spec.get("series_name") or spec.get("title"), 24) or "值"}],
    }


def _axes(spec: dict, categories: list[str], series: list[dict]) -> dict:
    y_axis: dict = {"type": "value", "name": _text(spec.get("y_name"), 20)}
    if series and series[0].get("type") == "bar":
        y_axis["min"] = 0
    else:
        y_axis["scale"] = True
    return {
        "xAxis": {"type": "category", "data": categories, "name": _text(spec.get("x_name"), 20)},
        "yAxis": y_axis,
        "series": series,
    }


_UNITS = {"℃", "W", "片", "g", "s", "%", "℃/W"}


def _tip(spec: dict, kind: str) -> dict:
    unit = _text(spec.get("unit"), 8)
    if not unit:
        named = _text(spec.get("y_name"), 8)
        unit = named if named in _UNITS else ""
    role = _text(spec.get("value_name"), 12)
    if kind == "heatmap":
        tip = {"unit": unit or "℃", "role": role or "均值"}
    elif kind == "boxplot":
        tip = {"unit": unit, "role": role or "箱线", "parts": ["最小值", "下四分位", "中位数", "上四分位", "最大值"]}
    elif kind == "spindle":
        tip = {"unit": unit or "℃", "role": role or "范围", "parts": ["最小值", "均值", "最大值"]}
    elif kind == "scatter":
        tip = {"unit": unit, "role": role or "单片"}
    elif kind == "pareto":
        tip = {"unit": "片", "role": role or "片数"}
    else:
        tip = {"unit": unit, "role": role}
    scope = _text(spec.get("scope"), 12)
    if scope:
        tip["scope"] = scope
    return tip


def _marks(option: dict, spec: dict, axis: str = "yAxis") -> None:
    raw = spec.get("marks")
    if not isinstance(raw, list) or not option["series"]:
        return
    lines = []
    for item in raw[:4]:
        if not isinstance(item, dict):
            continue
        value = _finite(item.get("y"))
        if value is None:
            continue
        lines.append({"name": _text(item.get("name"), 20) or "参考线", axis: value})
    if lines:
        option["series"][0]["markLine"] = {"symbol": "none", "data": lines}


def _categories_of(spec: dict) -> list[str]:
    raw = spec.get("categories")
    if not isinstance(raw, list):
        return []
    return [_text(item, 24) for item in raw[:_MAX_CATEGORIES]]


def _series_of(spec: dict) -> list[dict]:
    raw = spec.get("series")
    if not isinstance(raw, list):
        return []
    series = []
    for item in raw[:_MAX_SERIES]:
        if not isinstance(item, dict) or not isinstance(item.get("data"), list):
            continue
        series.append({"name": _text(item.get("name"), 24), "data": item["data"]})
    return series


def _box_row(raw: object) -> list[float] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) < 5:
        raise AppError(502, "AGENT_FAILED", "箱线需要 min、q1、median、q3、max")
    values = [_finite(item) for item in raw[:5]]
    if any(value is None for value in values):
        raise AppError(502, "AGENT_FAILED", "箱线里有非数字")
    return [_shown(float(value)) for value in values if value is not None]


def _point(raw: object) -> list[float | str] | None:
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    y = _finite(raw[1])
    if y is None:
        return None
    if isinstance(raw[0], str) and raw[0].strip():
        return [raw[0].strip()[:24], y]
    x = _finite(raw[0])
    if x is None:
        return None
    return [x, y]


def _fit_stored(option: object) -> dict:
    if not isinstance(option, dict):
        return {}
    fitted = _bar_baseline(_slot_axis(option))
    series = fitted.get("series") or []
    if any(isinstance(item, dict) and item.get("type") == "heatmap" for item in series):
        grid = dict(fitted.get("grid") or {})
        grid["containLabel"] = True
        grid["left"] = 8
        grid["bottom"] = 36
        fitted = {**fitted, "grid": grid}
    return fitted


def _bar_baseline(option: dict) -> dict:
    series = option.get("series")
    if not isinstance(series, list) or not series:
        return option
    if any(not isinstance(item, dict) or item.get("type") != "bar" for item in series):
        return option
    axis = option.get("yAxis")
    if not isinstance(axis, dict):
        return option
    return {**option, "yAxis": {**axis, "min": 0, "scale": False}}


def _slot_axis(option: dict) -> dict:
    axis = option.get("xAxis")
    series = option.get("series")
    if not isinstance(axis, dict) or axis.get("type") != "value" or not isinstance(series, list):
        return option
    if not series or any(item.get("type") != "scatter" for item in series if isinstance(item, dict)):
        return option
    named = bool(re.search(r"slot|槽", str(axis.get("name") or ""), re.I))
    labels: list[str] = []
    seen: set[str] = set()
    rewritten: list[tuple[dict, list[list[float | str]]]] = []
    for item in series:
        if not isinstance(item, dict):
            return option
        points: list[list[float | str]] = []
        for raw in item.get("data") or []:
            if not isinstance(raw, list) or len(raw) < 2:
                return option
            label = _slot_label(raw[0], named)
            y = _finite(raw[1])
            if label is None or y is None:
                return option
            points.append([label, y])
            if label not in seen:
                seen.add(label)
                labels.append(label)
        rewritten.append((item, points))
    if len(labels) < 1:
        return option
    labels.sort(key=_slot_order)
    updated = dict(option)
    updated["xAxis"] = {"type": "category", "data": labels, "name": "槽位"}
    updated["series"] = [{**item, "data": points} for item, points in rewritten]
    return updated


def _slot_label(value: object, named: bool) -> str | None:
    if isinstance(value, str):
        text = value.strip()[:24]
        if text and (named or "槽" in text):
            return text
        return None
    number = _finite(value)
    if number is None or number != int(number):
        return None
    slot = int(number)
    if named and 0 <= slot <= 32:
        return f"槽{slot}"
    return None


def _slot_order(label: str) -> tuple:
    machine = re.search(r"M(\d+)", label, re.I)
    slot = re.search(r"槽(\d+)", label)
    return (int(machine.group(1)) if machine else 0, int(slot.group(1)) if slot else 0, label)


def _cell(raw: object, x_count: int, y_count: int) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) < 3:
        return None
    if not isinstance(raw[0], int) or not isinstance(raw[1], int):
        return None
    if isinstance(raw[0], bool) or isinstance(raw[1], bool):
        return None
    value = _finite(raw[2])
    if value is None or raw[0] < 0 or raw[1] < 0 or raw[0] >= x_count or raw[1] >= y_count:
        return None
    return [raw[0], raw[1], _shown(value)]


def _label_list(raw: object) -> list[object]:
    return raw if isinstance(raw, list) else []


def _shown(value: float) -> float:
    return round(value, 2)


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _thin(points: list[list[float]], limit: int) -> list[list[float]]:
    if len(points) <= limit:
        return points
    step = len(points) / limit
    return [points[int(index * step)] for index in range(limit)]


def _text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _is_panel(value: object) -> bool:
    return isinstance(value, dict) and isinstance(value.get("option"), dict)
