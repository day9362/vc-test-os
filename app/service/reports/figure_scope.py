import re
from dataclasses import dataclass, field

from app.service.reports.analysis_math import item_sort_key

_MACHINE = re.compile(r"M\d+", re.I)
_SLOT = re.compile(r"(?:槽位|槽|slot)\s*(\d+)", re.I)
_TEMP = re.compile(r"Temp_?T(\d+)\s*[-−]\s*T(\d+)", re.I)
_BARE = re.compile(r"(?<![A-Za-z\d])T(\d+)\s*[-−]\s*T(\d+)", re.I)
_COLUMNS = ["项", "片数", "均值", "最小值", "最大值", "极差", "上限", "下限", "超上限", "超下限"]


@dataclass
class Prepared:
    records: list[dict]
    notes: list[str] = field(default_factory=list)
    narrowed: bool = False
    summary: dict | None = None


def uses_fixed_charts(prompt: str) -> bool:
    return bool((prompt or "").strip())


def chart_route(prompt: str) -> str:
    if asked_group(prompt):
        return "grouped"
    if _about_place(prompt):
        return "overview"
    return "machine_batch"


def asks_ambient(prompt: str) -> bool:
    return bool(re.search(r"室温|环境温度|Temp_Ta|(?<![A-Za-z\d])Ta(?![A-Za-z\d])", prompt or "", re.I))


def asked_group(prompt: str) -> str:
    text = prompt or ""
    if re.search(r"按[^，。]{0,12}(产品|批次)|分产品|分批次", text):
        return "batch"
    if re.search(r"按[^，。]{0,12}(机台槽位|槽位|槽)|分槽", text):
        return "slot"
    if re.search(r"按[^，。]{0,12}机台|分机台", text):
        return "machine"
    return ""


def prepare_records(prompt: str, records: list[dict], *, delta: bool = False) -> Prepared:
    if not delta and not uses_fixed_charts(prompt):
        return Prepared(records=records)
    asked_machines = {item.upper() for item in _MACHINE.findall(prompt)}
    asked_slots = {int(item) for item in _SLOT.findall(prompt)}
    asked_items = _asked_items(prompt)
    present = _present(records)
    notes: list[str] = []
    machines = asked_machines or set(present["machines"])
    slots = asked_slots or set(present["slots"])
    missing_machines = sorted(asked_machines - set(present["machines"]))
    missing_slots = sorted(asked_slots - set(present["slots"]))
    for name in missing_machines:
        notes.append(f"{name} 没有测过，未列入")
    for slot in missing_slots:
        notes.append(f"槽{slot} 没有测过，未列入")
    chosen: list[str] = []
    if asked_items:
        for name in asked_items:
            if name in present["limited"]:
                chosen.append(name)
            elif name in present["measured"]:
                notes.append(f"{name} 没有卡限，未列入")
                chosen.append(name)
            else:
                notes.append(f"{name} 没有这项数据，未列入")
    else:
        chosen = sorted(present["limited"], key=item_sort_key)
    filtered = _filter(records, machines, slots if asked_slots else None, chosen)
    if not filtered and notes:
        return Prepared(records=[], notes=notes, narrowed=bool(asked_machines or asked_slots))
    summary = _summary(filtered, notes, narrowed=bool(asked_machines or asked_slots), show_ambient=asks_ambient(prompt))
    return Prepared(records=filtered, notes=notes, narrowed=bool(asked_machines or asked_slots), summary=summary)


def _about_delta(prompt: str) -> bool:
    text = prompt or ""
    return "温差" in text or bool(_TEMP.search(text) or _BARE.search(text))


def _about_place(prompt: str) -> bool:
    text = prompt or ""
    return bool(_MACHINE.search(text) or _SLOT.search(text))


def _about_limit(prompt: str) -> bool:
    text = prompt or ""
    folded = text.lower()
    return "卡限" in text or "卡limit" in folded or bool(re.search(r"\blimit\b", folded))


def _asked_items(prompt: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for left, right in _TEMP.findall(prompt):
        item = f"Temp_T{int(left)}-T{int(right)}"
        if item not in seen:
            seen.add(item)
            found.append(item)
    for left, right in _BARE.findall(prompt):
        item = f"Temp_T{int(left)}-T{int(right)}"
        if item not in seen:
            seen.add(item)
            found.append(item)
    return found


def _present(records: list[dict]) -> dict:
    limited: set[str] = set()
    measured: set[str] = set()
    machines: set[str] = set()
    slots: set[int] = set()
    for record in records:
        machine = str(record.get("machine_id") or "")
        if machine:
            machines.add(machine)
        slot = record.get("slot_index")
        if isinstance(slot, int) and not isinstance(slot, bool):
            slots.add(slot)
        for item in _items(record.get("deltas")):
            measured.add(item["item"])
            if item.get("limited") is not False and (item.get("low") is not None or item.get("high") is not None):
                limited.add(item["item"])
        for item in _items(record.get("measured")):
            measured.add(item["item"])
    return {"limited": limited, "measured": measured, "machines": machines, "slots": slots}


def _filter(records: list[dict], machines: set[str], slots: set[int] | None, items: list[str]) -> list[dict]:
    wanted = set(items)
    filtered = []
    for record in records:
        machine = str(record.get("machine_id") or "")
        if machines and machine not in machines:
            continue
        slot = record.get("slot_index")
        if slots is not None and slot not in slots:
            continue
        deltas = [item for item in _items(record.get("deltas")) if item["item"] in wanted]
        measured = [item for item in _items(record.get("measured")) if item["item"] in wanted and item["item"] not in {row["item"] for row in deltas}]
        for item in measured:
            deltas.append({**item, "low": None, "high": None, "limited": False})
        if not deltas:
            continue
        copied = {**record, "deltas": deltas}
        copied.pop("measured", None)
        filtered.append(copied)
    return filtered


def _summary(records: list[dict], notes: list[str], *, narrowed: bool, show_ambient: bool = False) -> dict:
    serials = []
    failed = 0
    seen: set[str] = set()
    grouped: dict[str, list[dict]] = {}
    places: list[str] = []
    place_seen: set[str] = set()
    for record in records:
        serial = str(record.get("serial_number") or record.get("run_id") or "")
        if serial not in seen:
            seen.add(serial)
            serials.append(serial)
            if record.get("passed") is False:
                failed += 1
        machine = str(record.get("machine_id") or "")
        slot = record.get("slot_index")
        if machine and isinstance(slot, int) and not isinstance(slot, bool):
            label = f"{machine} 槽{slot}"
            if label not in place_seen:
                place_seen.add(label)
                places.append(label)
        for item in _items(record.get("deltas")):
            if item.get("limited") is False:
                continue
            grouped.setdefault(item["item"], []).append(item)
    where = "、".join(places) if narrowed and places else "本批全部槽位"
    names = [name for name in sorted(grouped, key=lambda name: _plan_key(name, grouped[name])) if show_ambient or name != "室温"]
    rows = [_row(name, grouped[name]) for name in names]
    if show_ambient and "室温" not in grouped:
        ambient = _ambient_row(records)
        if ambient:
            rows.append(ambient)
    return {
        "scope": f"测了 {len(serials)} 片，不合格 {failed} 片。{where}。",
        "columns": _COLUMNS,
        "rows": rows,
        "notes": notes,
    }


def _row(name: str, points: list[dict]) -> list[str]:
    values = [float(item["value"]) for item in points if isinstance(item.get("value"), (int, float)) and not isinstance(item.get("value"), bool)]
    high = _common(item.get("high") for item in points)
    low = _common(item.get("low") for item in points)
    high_fail = sum(1 for value in values if high is not None and value > high)
    low_fail = sum(1 for value in values if low is not None and value < low)
    if not values:
        return [name, "0 片", "—", "—", "—", "—", _temp(high), _temp(low), "0 片", "0 片"]
    mean = sum(values) / len(values)
    return [
        name,
        f"{len(values)} 片",
        _measure(name, mean),
        _measure(name, min(values)),
        _measure(name, max(values)),
        _measure(name, max(values) - min(values)),
        _measure(name, high),
        _measure(name, low),
        f"{high_fail} 片",
        f"{low_fail} 片",
    ]


def _plan_key(name: str, points: list[dict]) -> tuple:
    orders = [item["order"] for item in points if isinstance(item.get("order"), int) and not isinstance(item.get("order"), bool)]
    return (min(orders) if orders else 10**9, item_sort_key(name))


def _ambient_row(records: list[dict]) -> list[str] | None:
    values = [float(item) for item in (record.get("ambient") for record in records) if isinstance(item, (int, float)) and not isinstance(item, bool)]
    if not values:
        return None
    return [
        "室温",
        f"{len(values)} 片",
        _temp(sum(values) / len(values)),
        _temp(min(values)),
        _temp(max(values)),
        _temp(max(values) - min(values)),
        "—",
        "—",
        "—",
        "—",
    ]


def _measure(name: str, value: float | None) -> str:
    if value is None:
        return "—"
    unit = "W" if name == "power_w" else "℃"
    return f"{value:.3f} {unit}"


def _temp(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.3f} ℃"


def _common(values) -> float | None:
    numbers = [float(item) for item in values if isinstance(item, (int, float)) and not isinstance(item, bool)]
    if not numbers:
        return None
    return max(set(numbers), key=numbers.count)


def _items(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and str(item.get("item") or "").strip()]
