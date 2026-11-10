import json
import math
import random
import re
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import settings
from sqlalchemy import select

from app.models.orm.run import RunSampleOrm
from app.service.reports.analysis_math import _SAMPLE, item_sort_key, process_shape, usable
from app.core.errors import AppError

_NUMBER = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])")
_ITEM = re.compile(r"Temp_T\d+(?:-T\d+)?|power_w")
_PLAN = """你是测试数据分析员。下面只有各批的片数和这次的 mode。决定这次要取哪些结果。
只返回 json：{"focus": ["over_limit", "margin", "spread", "trend", "mean", "defect_rate"]}
mode 为 single 时不要选 mean，也不要选 defect_rate。
piece 为不足片时不要选 mean。
"""
_ASK = """你是测试数据分析员。先看已经给你的三张图和卡限项表。这是整批合计。要判断机台和槽位，自己去查，不要只根据这三张图和这张表下结论。
超上限、超下限：每一项超上限、超下限的片数。
均值和上下限：每一项的均值、最小值、最大值、上限、下限。
极差：柱底是最小值，柱顶是最大值，高度是极差。
卡限项表：每一项的片数、均值、最小、最大、极差、上限、下限、超限片数。
单批次只做两步。超限片数大于 0 的项，每一项先查一次机台和槽位：{"tool":"place","item":"项名"}。没查完不要写结论。查完不要再查单片或过程曲线，立刻按下面的句式写结论。
每个超限项在 exposed 里只写一句：项名，超限在哪些机台、哪些槽，带上查到的片数。这一项的最小值已经高于上限，或最大值已经低于下限，接「整批被抬高」或「整批被压低」，再接「怀疑产品问题」。超限集中在一台机，接「怀疑这台机」，并写出这台机各槽的超限片数。超限集中在几个槽，直接写出这些槽位和片数，接「怀疑这些槽位」。
已经超限的项只放进 exposed，不要放进 risk。risk 只写还没超限、但最大值贴近上限或最小值贴近下限的项，一句一项。没有就写空数组。表上已有的超限片数、均值、极差不要单独再抄一遍。
每次只返回一个 json。
查机台和槽位：{"tool":"place","item":"项名"}。返回这一项各机台、各槽位的片数、超限片数、均值、最小值、最大值。
写结论：{"exposed":["已经发生的问题"],"risk":["还没发生、但值得注意的问题"]}。没有就写空数组。
数字、片数、限值、机台、槽位必须来自这三张图、这张表或查到的结果，并带上单位。没有的不要写。
某一批不足 30 片时，只写这几片看到的情况。
单批次：不要比较批次，每个批次单独分析。
跨批次也先查超限项的机台和槽位，一项查一次。按同一项对齐：两批都整批过限，怀疑产品问题；只出在一批的一台机，怀疑这台机；只出在一批的几个槽，怀疑这些槽位。不写哪一批更好。
"""
_EXPOSED = "已暴露的卡限项"
_RISK = "潜在危险项"
_TOOL_LABEL = {"page": "报告概览", "place": "机台槽位", "results": "结果数据", "process": "过程数据"}
_FAIL_SHOWN = 8
_PASS_SAMPLE = 5
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


def _shown(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    text = json.dumps(float(value))
    return text.rstrip("0").rstrip(".") if "." in text else text


def _unit(name: str) -> str:
    if name == "power_w":
        return " W"
    if name == "室温" or name.startswith("Temp_"):
        return " ℃"
    return ""


def _cell_fails(cell: dict) -> int:
    return int(cell.get("high_fail") or 0) + int(cell.get("low_fail") or 0)


def _place_cells(place: dict | None, batch: str) -> tuple[list[dict], list[dict]]:
    machines: list[dict] = []
    slots: list[dict] = []
    for block in (place or {}).get("batches") or []:
        if not isinstance(block, dict) or (batch and block.get("batch") != batch):
            continue
        machines.extend(cell for cell in block.get("machines") or [] if isinstance(cell, dict))
        slots.extend(cell for cell in block.get("slots") or [] if isinstance(cell, dict))
    return machines, slots


def _keep(values: list, value: object) -> str:
    number = _num(value)
    if number is None:
        return ""
    values.append(number)
    return _shown(number)


def _window(item: dict) -> float | None:
    high, low = item.get("high"), item.get("low")
    if isinstance(high, (int, float)) and isinstance(low, (int, float)) and high > low:
        return float(high) - float(low)
    return None


def _kind(item: dict, machines: list[dict]) -> str:
    minimum, maximum = item.get("minimum"), item.get("maximum")
    high, low = item.get("high"), item.get("low")
    if isinstance(minimum, (int, float)) and isinstance(high, (int, float)) and minimum > high:
        return "product"
    if isinstance(maximum, (int, float)) and isinstance(low, (int, float)) and maximum < low:
        return "product"
    ranked = [cell for cell in machines if int(cell.get("n") or 0)]
    if ranked and all(_cell_fails(cell) * 10 >= int(cell["n"]) * 9 for cell in ranked):
        return "product"
    total = sum(_cell_fails(cell) for cell in machines)
    lead = max(machines, key=lambda cell: _cell_fails(cell), default=None)
    if lead and total and _cell_fails(lead) * 5 >= total * 4 and all(_cell_fails(cell) * 5 < total for cell in machines if cell is not lead):
        return "machine"
    return "slots"


def _slot_sort_key(name: str) -> tuple:
    machine, _, index = str(name).partition("#")
    return (machine, int(index) if index.isdigit() else 0, str(name))


def _remember_index(values: list, index: str) -> None:
    if index.isdigit():
        _keep(values, int(index))


def _slot_label(names: list[str], values: list) -> str:
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for name in sorted((str(item) for item in names), key=_slot_sort_key):
        machine, _, index = name.partition("#")
        if machine not in grouped:
            grouped[machine] = []
            order.append(machine)
        if index:
            grouped[machine].append(index)
            _remember_index(values, index)
    return "、".join(machine + ("#" + "#".join(grouped[machine]) if grouped[machine] else "") for machine in order)


def _slot_count_label(cells: list[dict], values: list) -> str:
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for cell in sorted(cells, key=lambda item: _slot_sort_key(str(item.get("name") or ""))):
        machine, _, index = str(cell.get("name") or "").partition("#")
        count = _keep(values, _cell_fails(cell))
        _remember_index(values, index)
        piece = f"#{index}（{count} 片）" if index else f"（{count} 片）"
        if machine not in grouped:
            grouped[machine] = []
            order.append(machine)
        grouped[machine].append(piece)
    return "、".join(machine + "".join(grouped[machine]) for machine in order)


def _join(parts: list[str]) -> str:
    return "".join(part for part in parts if part)


def _spread_text(item: dict, slots: list[dict], values: list) -> list[str]:
    unit = _unit(str(item.get("item") or ""))
    span = item.get("range")
    window = _window(item)
    ranges = [_num(float(cell["maximum"]) - float(cell["minimum"])) for cell in slots if isinstance(cell.get("maximum"), (int, float)) and isinstance(cell.get("minimum"), (int, float))]
    means = [_num(cell.get("mean")) for cell in slots if isinstance(cell.get("mean"), (int, float))]
    parts = []
    if ranges:
        low, high = min(ranges), max(ranges)
        if low == high:
            parts.append(f"同一槽里的极差 {_keep(values, low)}{unit}")
        else:
            parts.append(f"同一槽里的极差从 {_keep(values, low)}{unit} 到 {_keep(values, high)}{unit}")
    if len(means) >= 2 and max(means) != min(means):
        parts.append(f"各槽均值从 {_keep(values, min(means))}{unit} 到 {_keep(values, max(means))}{unit}，差 {_keep(values, max(means) - min(means))}{unit}")
    if isinstance(span, (int, float)):
        parts.append(f"整批极差 {_keep(values, span)}{unit}")
    if not parts:
        return []
    lines = ["，".join(parts) + "。"]
    if window is not None and isinstance(span, (int, float)) and span >= window / 2:
        lines.append("这个波动大，来自槽内起伏和槽与槽的水平差。")
    elif window is not None and isinstance(span, (int, float)) and span < window / 4:
        lines.append("极差不大，分布很齐。")
    return lines


def _product_paragraph(items: list[dict], places: dict[str, dict], batch: str, rows: list[dict], values: list) -> list[str]:
    ordered = sorted(items, key=lambda item: item_sort_key(str(item.get("item") or "")))
    names = [str(item.get("item") or "") for item in ordered]
    title = " 和 ".join(names) if len(names) > 1 else names[0]
    lines = [f"{title} 是整批一起过限，怀疑产品问题。"]
    for item in ordered:
        name = str(item.get("item") or "")
        unit = _unit(name)
        machines, slots = _place_cells(places.get(name), batch)
        failing = [cell for cell in machines if _cell_fails(cell)]
        bits = []
        full = [cell for cell in failing if int(cell.get("n") or 0) and _cell_fails(cell) == int(cell["n"])]
        if full and len(full) == len(failing):
            sizes = {int(cell["n"]) for cell in full}
            if len(sizes) == 1:
                bits.append("、".join(str(cell.get("name") or "") for cell in full) + f" 各 {_keep(values, full[0].get('n'))} 片全部超限")
            else:
                bits.append("、".join(f"{cell.get('name')} {_keep(values, cell.get('n'))} 片全部超限" for cell in full))
        elif item.get("high_fail"):
            bits.append(f"{_keep(values, item.get('high_fail'))} 片超上限")
        if isinstance(item.get("minimum"), (int, float)):
            bits.append(f"最低 {_keep(values, item.get('minimum'))}{unit}")
        if isinstance(item.get("mean"), (int, float)):
            bits.append(f"均值 {_keep(values, item.get('mean'))}{unit}")
        if isinstance(item.get("range"), (int, float)):
            bits.append(f"极差 {_keep(values, item.get('range'))}{unit}")
        if isinstance(item.get("high"), (int, float)):
            bits.append(f"上限 {_keep(values, item.get('high'))}{unit}")
        block = [f"{name}：" + "，".join(bit for bit in bits if bit) + "。"]
        spread = _spread_text(item, slots, values)
        block.extend(spread)
        minimum, maximum = item.get("minimum"), item.get("maximum")
        high, low = item.get("high"), item.get("low")
        lifted = isinstance(minimum, (int, float)) and isinstance(high, (int, float)) and minimum > high
        pressed = isinstance(maximum, (int, float)) and isinstance(low, (int, float)) and maximum < low
        if lifted:
            block.append("最低值已经高于上限，排除只是少数片子超出去。")
        elif pressed:
            block.append("最高值已经低于下限，排除只是少数片子偏低。")
        elif any("极差不大" in line for line in spread):
            block.append("排除少数片子在跳，是整批被抬高。")
        elif any("波动大" in line for line in spread):
            block.append("排除整批只是被一起平移。")
        if len([cell for cell in machines if int(cell.get("n") or 0)]) >= 2:
            block.append("各机台都过限，排除某一台机。")
        quiet = _quiet_slots(rows, batch, name)
        if quiet and name != "室温":
            cause = "温差才跟着超" if name.startswith("Temp_") else "这一项才跟着超"
            block.append(f"室温没有超限的槽也有超限：{_slot_label(quiet, values)}。排除室温太高，{cause}。")
        higher = _higher_machine(machines, values, unit)
        if higher:
            block.append(higher)
        lines.append(_join(block))
    return lines


def _quiet_slots(rows: list[dict], batch: str, item: str) -> list[str]:
    ambient: dict[str, list[int]] = {}
    target: dict[str, list[int]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if str(row.get("batch_id") or "") != batch:
            continue
        name = str(row.get("item") or "")
        if name not in {item, "室温"}:
            continue
        run_id = str(row.get("run_id") or "")
        mark = (run_id, name)
        if not run_id or mark in seen:
            continue
        seen.add(mark)
        slot = str(row.get("slot_name") or "")
        bucket = ambient if name == "室温" else target
        cell = bucket.setdefault(slot, [0, 0])
        cell[0] += 1
        if _outside(row):
            cell[1] += 1
    found = []
    for slot, counts in target.items():
        room = ambient.get(slot)
        if room and room[1] == 0 and counts[1]:
            found.append(slot)
    return sorted(found)


def _higher_machine(machines: list[dict], values: list, unit: str) -> str:
    scored = [cell for cell in machines if isinstance(cell.get("mean"), (int, float))]
    if len(scored) < 2:
        return ""
    scored.sort(key=lambda cell: float(cell["mean"]))
    gap = _num(float(scored[-1]["mean"]) - float(scored[0]["mean"]))
    if gap is None or gap < 0.05:
        return ""
    return f"{scored[-1].get('name')} 的均值 {_keep(values, scored[-1].get('mean'))}{unit}，比 {scored[0].get('name')} 的 {_keep(values, scored[0].get('mean'))}{unit} 高 {_keep(values, gap)}{unit}。这是整批过限之上再高的一截，排除只是这一台机的问题。"


def _machine_paragraph(item: dict, place: dict | None, batch: str, rows: list[dict], values: list) -> list[str]:
    name = str(item.get("item") or "")
    unit = _unit(name)
    machines, slots = _place_cells(place, batch)
    ranked = sorted(machines, key=lambda cell: (-_cell_fails(cell), str(cell.get("name") or "")))
    lead = ranked[0]
    own = [cell for cell in slots if str(cell.get("name") or "").startswith(f"{lead.get('name')}#") and _cell_fails(cell)]
    slot_text = _slot_count_label(own, values)
    others = [cell for cell in ranked[1:] if _cell_fails(cell)]
    quiet_machines = [cell for cell in ranked[1:] if not _cell_fails(cell)]
    other_text = "、".join(f"{cell.get('name')} {_keep(values, _cell_fails(cell))} 片" for cell in others)
    block = [f"{name} 集中在 {lead.get('name')}，怀疑这台机。"]
    block.append(f"{_keep(values, sum(_cell_fails(cell) for cell in ranked))} 片超限里有 {_keep(values, _cell_fails(lead))} 片在 {lead.get('name')}，{slot_text}。")
    if other_text:
        block.append(f"其余机台 {other_text}，只有零星超限，排除整批产品问题。")
    elif quiet_machines:
        block.append(f"其余机台 {'、'.join(str(cell.get('name') or '') for cell in quiet_machines)} 没有超限，排除整批产品问题。")
    if name != "室温":
        room = _room_exclusion(rows, batch, name, values)
        if room:
            block.append(room)
    resting = _resting_machines(ranked[1:], item, values, unit)
    if resting:
        block.append(resting)
    return [_join(block)]


def _room_exclusion(rows: list[dict], batch: str, item: str, values: list) -> str:
    cause = "温差才跟着超" if item.startswith("Temp_") else "这一项才跟着超"
    quiet = _quiet_slots(rows, batch, item)
    inside = _inside_ambient(rows, batch, item)
    bits = []
    if quiet:
        bits.append(f"室温没有超限的槽也有超限：{_slot_label(quiet, values)}")
    if inside:
        bits.append(f"超限的片子里有 {_keep(values, inside)} 片当时室温还在限内")
    if not bits:
        return ""
    return "，".join(bits) + f"。排除室温太高，{cause}。"


def _inside_ambient(rows: list[dict], batch: str, item: str) -> int:
    grouped: dict[str, dict[str, dict]] = {}
    for row in rows:
        if str(row.get("batch_id") or "") != batch:
            continue
        run_id = str(row.get("run_id") or "")
        name = str(row.get("item") or "")
        if run_id and name in {item, "室温"}:
            grouped.setdefault(run_id, {})[name] = row
    count = 0
    for wafer in grouped.values():
        if item in wafer and "室温" in wafer and _outside(wafer[item]) and not _outside(wafer["室温"]):
            count += 1
    return count


def _resting_machines(machines: list[dict], item: dict, values: list, unit: str) -> str:
    high = item.get("high")
    span = item.get("range")
    if not isinstance(high, (int, float)) or not isinstance(span, (int, float)):
        return ""
    close = [cell for cell in machines if isinstance(cell.get("maximum"), (int, float)) and float(high) - float(cell["maximum"]) < span]
    if not close:
        return ""
    bits = []
    for cell in close:
        piece = str(cell.get("name") or "")
        if isinstance(cell.get("mean"), (int, float)):
            piece += f" 均值 {_keep(values, cell.get('mean'))}{unit}"
        piece += f"，最高 {_keep(values, cell.get('maximum'))}{unit}"
        bits.append(piece)
    return f"{'；'.join(bits)}。贴着上限 {_keep(values, high)}{unit}，是还没展开的风险，排除已经和超限机台一样过限。"


def _slot_paragraph(item: dict, place: dict | None, batch: str, values: list) -> list[str]:
    name = str(item.get("item") or "")
    unit = _unit(name)
    _machines, slots = _place_cells(place, batch)
    hot = [cell for cell in slots if _cell_fails(cell)]
    quiet = len(slots) - len(hot)
    slot_text = _slot_count_label(hot, values)
    block = [f"{name} 超限集中在 {slot_text}，怀疑这些槽位。"]
    counts = []
    if item.get("high_fail"):
        counts.append(f"{_keep(values, item.get('high_fail'))} 片超过上限 {_keep(values, item.get('high'))}{unit}")
    if item.get("low_fail"):
        counts.append(f"{_keep(values, item.get('low_fail'))} 片低于下限 {_keep(values, item.get('low'))}{unit}")
    low_clear = not item.get("low_fail") and isinstance(item.get("low"), (int, float))
    if low_clear:
        counts.append(f"没有低于下限 {_keep(values, item.get('low'))}{unit}")
    if quiet:
        counts.append(f"其余 {_keep(values, quiet)} 个槽是 0")
    if counts:
        block.append("，".join(counts) + "。")
    if low_clear:
        block.append("排除室温过低。" if name == "室温" else "排除偏低。")
    if quiet:
        block.append("这些槽以外没有超限，排除整批一起超限。")
    if _mixed_machines(slots):
        block.append("同一台机里有的槽没有超限，排除某一台机。")
    spread = _spread_text(item, slots, values)
    block.extend(spread)
    if any("极差不大" in line for line in spread):
        block.append("排除少数片子在跳。")
    elif any("波动大" in line for line in spread):
        block.append("排除整批只是被一起平移。")
    return [_join(block)]


def _mixed_machines(slots: list[dict]) -> bool:
    seen: dict[str, set[bool]] = {}
    for cell in slots:
        machine = str(cell.get("name") or "").split("#", 1)[0]
        if machine:
            seen.setdefault(machine, set()).add(bool(_cell_fails(cell)))
    return any(len(flags) > 1 for flags in seen.values())


def _limit_note(items: list[dict], values: list) -> list[str]:
    held = [item for item in items if not (int(item.get("high_fail") or 0) + int(item.get("low_fail") or 0))]
    far = []
    for item in held:
        span = item.get("range")
        high, maximum = item.get("high"), item.get("maximum")
        if not all(isinstance(value, (int, float)) for value in (span, high, maximum)):
            continue
        gap = _num(float(high) - float(maximum))
        if gap is None or gap < 0 or gap < span:
            continue
        far.append((gap, item))
    if not far:
        return []
    gap, item = min(far, key=lambda pair: pair[0])
    name = str(item.get("item") or "")
    unit = _unit(name)
    detail = f"{name} 最大 {_keep(values, item.get('maximum'))}{unit}，离上限 {_keep(values, item.get('high'))}{unit} 还有 {_keep(values, gap)}{unit}。离上限的距离大于这一项的极差，排除贴近上限。"
    wide = False
    for _, held_item in far:
        window = _window(held_item)
        span = held_item.get("range")
        if window is not None and isinstance(span, (int, float)) and span >= window / 2:
            wide = True
    tail = "其余限内项离上限的距离都大于各自的极差，排除贴近上限。"
    if not wide:
        tail = "其余限内项离上限的距离都大于各自的极差，排除贴近上限，也排除波动大。"
    return [detail, tail]


def _opening(batch: dict, census: dict | None, values: list, heading: str | None = None, method: bool = True) -> list[str]:
    tested = batch.get("tested")
    if not isinstance(tested, int) or not tested:
        return []
    rate = batch.get("yield_rate")
    slots = list((census or {}).get("slots") or [])
    machines: dict[str, list[dict]] = {}
    for slot in slots:
        machine = str(slot.get("slot") or "").split("#", 1)[0]
        if machine:
            machines.setdefault(machine, []).append(slot)
    head = f"{heading or ('本批 ' + str(batch.get('batch') or ''))} 共 {_keep(values, tested)} 片"
    if isinstance(rate, (int, float)):
        head += f"，整体良率 {_keep(values, rate)}%"
    if machines:
        counts = {len(group) for group in machines.values()}
        wafers = {int(slot.get("tested") or 0) for group in machines.values() for slot in group}
        names = "、".join(sorted(machines))
        if len(counts) == 1 and len(wafers) == 1:
            head += f"。机台 {names}，各 {_keep(values, counts.pop())} 个槽，每槽 {_keep(values, wafers.pop())} 片"
        else:
            head += f"。机台 {names}"
    lines = [head + "。"]
    if method:
        lines.append("先看超限项，再按机台和槽位拆开，最后看极差是整批被抬高，还是少数片子在跳。")
    return lines


def render_single(run: "SummaryRun") -> str:
    page = run.results[0]["result"] if run.results else {}
    places: dict[str, dict] = {}
    for entry in run.results:
        result = entry.get("result") if isinstance(entry, dict) else None
        if isinstance(entry, dict) and entry.get("tool") == "place" and isinstance(result, dict) and result.get("item"):
            places[str(result["item"])] = result
    values: list = []
    batches = [batch for batch in page.get("batches") or [] if isinstance(batch, dict)]
    census = {str(item.get("batch") or ""): item for item in run.payload.get("census") or [] if isinstance(item, dict)}
    sections: list[tuple[list[str], list[str]]] = []
    for batch in batches:
        exposed: list[str] = []
        risk: list[str] = []
        name = str(batch.get("batch") or "")
        exposed.extend(_opening(batch, census.get(name), values))
        items = [item for item in batch.get("items") or [] if isinstance(item, dict) and item.get("item")]
        if not items:
            exposed.append(f"本批 {name} 没有取到卡限项，这次对不齐。")
            sections.append((exposed, risk))
            continue
        failing = [item for item in items if int(item.get("high_fail") or 0) + int(item.get("low_fail") or 0)]
        failing.sort(key=lambda item: item_sort_key(str(item.get("item") or "")))
        grouped: dict[str, list[dict]] = {"product": [], "machine": [], "slots": []}
        for item in failing:
            machines, _slots = _place_cells(places.get(str(item.get("item") or "")), name)
            grouped[_kind(item, machines)].append(item)
        if grouped["product"]:
            exposed.extend(_product_paragraph(grouped["product"], places, name, run.rows, values))
        for item in sorted(grouped["machine"], key=lambda entry: item_sort_key(str(entry.get("item") or ""))):
            exposed.extend(_machine_paragraph(item, places.get(str(item.get("item") or "")), name, run.rows, values))
        for item in sorted(grouped["slots"], key=lambda entry: item_sort_key(str(entry.get("item") or ""))):
            exposed.extend(_slot_paragraph(item, places.get(str(item.get("item") or "")), name, values))
        for item in items:
            if int(item.get("high_fail") or 0) + int(item.get("low_fail") or 0):
                continue
            near = _near_line(item, values)
            if near:
                risk.append(near)
        risk.extend(_limit_note(items, values))
        sections.append((exposed, risk))
    if values:
        run.results.append({"tool": "derived", "result": {"values": values}})
    if len(sections) < 2:
        exposed, risk = sections[0] if sections else ([], [])
        return conclusion_text({"exposed": exposed, "risk": risk})
    lines: list[str] = []
    for exposed, risk in sections:
        lines.append(_EXPOSED)
        lines.extend(exposed or ["这次没有已经超限的项。"])
        lines.append(_RISK)
        lines.extend(risk or ["没有潜在危险项。"])
    return json.dumps({"lines": lines}, ensure_ascii=False)


_BATCH_MARKS = "一二三四五六"


def _batch_label(index: int) -> str:
    if index < len(_BATCH_MARKS):
        return f"批次{_BATCH_MARKS[index]}"
    return f"批次{index + 1}"


def _fail_count(item: dict) -> int:
    return int(item.get("high_fail") or 0) + int(item.get("low_fail") or 0)


def _over_bits(item: dict, machines: list[dict], values: list) -> list[str]:
    unit = _unit(str(item.get("item") or ""))
    failing = [cell for cell in machines if _cell_fails(cell)]
    bits = []
    full = [cell for cell in failing if int(cell.get("n") or 0) and _cell_fails(cell) == int(cell["n"])]
    if full and len(full) == len(failing):
        sizes = {int(cell["n"]) for cell in full}
        if len(sizes) == 1:
            bits.append("、".join(str(cell.get("name") or "") for cell in full) + f" 各 {_keep(values, full[0].get('n'))} 片全部超限")
        else:
            bits.append("、".join(f"{cell.get('name')} {_keep(values, cell.get('n'))} 片全部超限" for cell in full))
    elif item.get("high_fail"):
        bits.append(f"{_keep(values, item.get('high_fail'))} 片超上限")
    if isinstance(item.get("minimum"), (int, float)):
        bits.append(f"最低 {_keep(values, item.get('minimum'))}{unit}")
    if isinstance(item.get("mean"), (int, float)):
        bits.append(f"均值 {_keep(values, item.get('mean'))}{unit}")
    if isinstance(item.get("range"), (int, float)):
        bits.append(f"极差 {_keep(values, item.get('range'))}{unit}")
    if isinstance(item.get("high"), (int, float)):
        bits.append(f"上限 {_keep(values, item.get('high'))}{unit}")
    return bits


def _shift_line(item: dict, spread: list[str], kind: str) -> str:
    minimum, maximum = item.get("minimum"), item.get("maximum")
    high, low = item.get("high"), item.get("low")
    if isinstance(minimum, (int, float)) and isinstance(high, (int, float)) and minimum > high:
        return "最低值已经高于上限，排除只是少数片子超出去。"
    if isinstance(maximum, (int, float)) and isinstance(low, (int, float)) and maximum < low:
        return "最高值已经低于下限，排除只是少数片子偏低。"
    if any("极差不大" in line for line in spread):
        return "排除少数片子在跳，是整批被抬高。" if kind == "product" else "排除少数片子在跳。"
    if any("波动大" in line for line in spread):
        return "排除整批只是被一起平移。"
    return ""


def _cross_views(name: str, pairs: list[tuple[dict, dict]], labels: dict[str, str], places: dict[str, dict], values: list) -> list[dict]:
    views = []
    for batch, item in pairs:
        batch_id = str(batch.get("batch") or "")
        machines, slots = _place_cells(places.get(name), batch_id)
        kind = _kind(item, machines) if _fail_count(item) else "ok"
        ranked = sorted(machines, key=lambda cell: (-_cell_fails(cell), str(cell.get("name") or "")))
        lead = str(ranked[0].get("name") or "") if ranked and _cell_fails(ranked[0]) else ""
        hot = [cell for cell in slots if _cell_fails(cell)]
        views.append({
            "batch": batch,
            "item": item,
            "id": batch_id,
            "label": labels.get(batch_id, batch_id),
            "kind": kind,
            "machines": machines,
            "slots": slots,
            "lead": lead,
            "hot": hot,
            "hot_text": _slot_count_label(hot, values) if hot else "",
        })
    return views


def _cross_judgment(name: str, views: list[dict]) -> str:
    failing = [view for view in views if view["kind"] != "ok"]
    if not failing:
        return ""
    kinds = {view["kind"] for view in failing}
    if len(failing) == len(views) and kinds == {"product"} and len(failing) >= 2:
        word = "两批" if len(failing) == 2 else "各批"
        return f"{name} {word}都是整批一起过限，怀疑产品问题。"
    if len(failing) == 1:
        view = failing[0]
        if view["kind"] == "product":
            return f"{name} 只出在{view['label']}，整批一起过限，怀疑产品问题。"
        if view["kind"] == "machine":
            return f"{name} 只出在{view['label']}的 {view['lead']}，怀疑这台机。"
        return f"{name} 只出在{view['label']}的 {view['hot_text']}，怀疑这些槽位。"
    if kinds == {"machine"} and len({view["lead"] for view in failing}) == 1:
        return f"{name} {'、'.join(view['label'] for view in failing)}都集中在 {failing[0]['lead']}，怀疑这台机。"
    parts = []
    for view in failing:
        if view["kind"] == "product":
            parts.append(f"{view['label']}是整批一起过限，怀疑产品问题。")
        elif view["kind"] == "machine":
            parts.append(f"{view['label']}集中在 {view['lead']}，怀疑这台机。")
        else:
            parts.append(f"{view['label']}超限集中在 {view['hot_text']}，怀疑这些槽位。")
    return f"{name} " + "".join(parts)


def _product_fact(view: dict, rows: list[dict], values: list) -> str:
    item = view["item"]
    name = str(item.get("item") or "")
    block = []
    if view["batch"].get("piece") == "不足片":
        block.append(f"{view['label']}片数不足，只写这几片看到的情况。")
    bits = _over_bits(item, view["machines"], values)
    block.append(f"{view['label']}：" + "，".join(bit for bit in bits if bit) + "。")
    spread = _spread_text(item, view["slots"], values)
    block.extend(spread)
    shift = _shift_line(item, spread, "product")
    if shift:
        block.append(shift)
    quiet = _quiet_slots(rows, view["id"], name) if name != "室温" else []
    if quiet:
        cause = "温差才跟着超" if name.startswith("Temp_") else "这一项才跟着超"
        block.append(f"室温没有超限的槽也有超限：{_slot_label(quiet, values)}。排除室温太高，{cause}。")
    higher = _higher_machine(view["machines"], values, _unit(name))
    if higher:
        block.append(higher)
    return _join(block)


def _machine_fact(view: dict, rows: list[dict], values: list) -> str:
    item = view["item"]
    name = str(item.get("item") or "")
    unit = _unit(name)
    ranked = sorted(view["machines"], key=lambda cell: (-_cell_fails(cell), str(cell.get("name") or "")))
    if not ranked:
        return ""
    lead = ranked[0]
    others = [cell for cell in ranked[1:] if _cell_fails(cell)]
    quiet = [cell for cell in ranked[1:] if not _cell_fails(cell)]
    other_text = "、".join(f"{cell.get('name')} {_keep(values, _cell_fails(cell))} 片" for cell in others)
    block = []
    if view["batch"].get("piece") == "不足片":
        block.append(f"{view['label']}片数不足，只写这几片看到的情况。")
    own = [cell for cell in view["slots"] if str(cell.get("name") or "").startswith(f"{lead.get('name')}#") and _cell_fails(cell)]
    slot_text = _slot_count_label(own, values)
    block.append(f"{view['label']}：{_keep(values, sum(_cell_fails(cell) for cell in ranked))} 片超限里有 {_keep(values, _cell_fails(lead))} 片在 {lead.get('name')}" + (f"，{slot_text}。" if slot_text else "。"))
    if other_text:
        block.append(f"其余机台 {other_text}，只有零星超限，排除整批产品问题。")
    elif quiet:
        block.append(f"其余机台 {'、'.join(str(cell.get('name') or '') for cell in quiet)} 没有超限，排除整批产品问题。")
    if name != "室温":
        room = _room_exclusion(rows, view["id"], name, values)
        if room:
            block.append(room)
    resting = _resting_machines(ranked[1:], item, values, unit)
    if resting:
        block.append(resting)
    return _join(block)


def _slot_fact(view: dict, values: list) -> str:
    item = view["item"]
    name = str(item.get("item") or "")
    unit = _unit(name)
    quiet = len(view["slots"]) - len(view["hot"])
    block = []
    if view["batch"].get("piece") == "不足片":
        block.append(f"{view['label']}片数不足，只写这几片看到的情况。")
    counts = []
    if item.get("high_fail"):
        counts.append(f"{_keep(values, item.get('high_fail'))} 片超过上限 {_keep(values, item.get('high'))}{unit}")
    if item.get("low_fail"):
        counts.append(f"{_keep(values, item.get('low_fail'))} 片低于下限 {_keep(values, item.get('low'))}{unit}")
    elif isinstance(item.get("low"), (int, float)):
        counts.append(f"没有低于下限 {_keep(values, item.get('low'))}{unit}")
    if quiet:
        counts.append(f"其余 {_keep(values, quiet)} 个槽是 0")
    block.append(f"{view['label']}：" + "，".join(counts) + "。" if counts else f"{view['label']}：{view['hot_text']}。")
    if isinstance(item.get("low"), (int, float)) and not item.get("low_fail"):
        block.append("排除室温过低。" if name == "室温" else "排除偏低。")
    if quiet:
        block.append("这些槽以外没有超限，排除整批一起超限。")
    if _mixed_machines(view["slots"]):
        block.append("同一台机里有的槽没有超限，排除某一台机。")
    spread = _spread_text(item, view["slots"], values)
    block.extend(spread)
    shift = _shift_line(item, spread, "slots")
    if shift:
        block.append(shift)
    return _join(block)


def _clear_fact(view: dict, values: list) -> str:
    item = view["item"]
    unit = _unit(str(item.get("item") or ""))
    bits = []
    if isinstance(item.get("maximum"), (int, float)):
        bits.append(f"最高 {_keep(values, item.get('maximum'))}{unit}")
    if isinstance(item.get("mean"), (int, float)):
        bits.append(f"均值 {_keep(values, item.get('mean'))}{unit}")
    body = "，".join(bits)
    return f"{view['label']}：{body}，没有超限。" if body else f"{view['label']}没有超限。"


def _limit_diff(views: list[dict], values: list, unit: str) -> str:
    parts = []
    for side, word in (("high", "上限"), ("low", "下限")):
        known = [(view["label"], view["item"].get(side)) for view in views if isinstance(view["item"].get(side), (int, float))]
        if len({value for _, value in known}) > 1:
            parts.append("，".join(f"{label}{word} {_keep(values, value)}{unit}" for label, value in known))
    return "。".join(parts) + "。" if parts else ""


def _mean_gap(views: list[dict], values: list, unit: str) -> str:
    scored = [view for view in views if isinstance(view["item"].get("mean"), (int, float))]
    if len(scored) < 2:
        return ""
    scored.sort(key=lambda view: float(view["item"]["mean"]))
    gap = _num(float(scored[-1]["item"]["mean"]) - float(scored[0]["item"]["mean"]))
    if gap is None or gap == 0:
        return "两批均值相同。" if len(scored) == 2 else "各批均值相同。"
    ranges = [float(view["item"]["range"]) for view in scored if isinstance(view["item"].get("range"), (int, float))]
    text = f"{scored[-1]['label']}均值比{scored[0]['label']}高 {_keep(values, gap)}{unit}。"
    if ranges and gap < min(ranges):
        text += "这个差距小于各自极差。"
    return text


def _machine_sets(views: list[dict]) -> str:
    sets = []
    for view in views:
        names = sorted(str(cell.get("name") or "") for cell in view["machines"] if int(cell.get("n") or 0))
        if names:
            sets.append((view["label"], names))
    if len(sets) < 2:
        return ""
    if len({tuple(names) for _, names in sets}) > 1:
        text = "，".join(f"{label}是 {'、'.join(names)}" for label, names in sets)
        return f"{text}，换了机台仍然整批抬高，排除某一台机。"
    return f"各批机台都是 {'、'.join(sets[0][1])}，各机台都过限，排除某一台机。"


def _slot_contrast(view: dict, names: list[str], values: list) -> str:
    found = {str(cell.get("name") or ""): cell for cell in view["slots"]}
    clear = [name for name in names if name in found and not _cell_fails(found[name])]
    missing = [name for name in names if name not in found]
    bits = []
    if clear:
        bits.append(f"{view['label']}的 {_slot_label(clear, values)} 没有超限")
    if missing:
        bits.append(f"{view['label']}没有 {_slot_label(missing, values)}")
    return "，".join(bits) + "。" if bits else ""


def _cross_item(name: str, pairs: list[tuple[dict, dict]], labels: dict[str, str], places: dict[str, dict], rows: list[dict], values: list) -> str:
    views = _cross_views(name, pairs, labels, places, values)
    failing = [view for view in views if view["kind"] != "ok"]
    clear = [view for view in views if view["kind"] == "ok"]
    block = [_cross_judgment(name, views)]
    diff = _limit_diff(views, values, _unit(name))
    if diff:
        block.append(diff)
    for view in failing:
        if view["kind"] == "product":
            block.append(_product_fact(view, rows, values))
        elif view["kind"] == "machine":
            block.append(_machine_fact(view, rows, values))
        else:
            block.append(_slot_fact(view, values))
    if len(failing) >= 2 and {view["kind"] for view in failing} == {"product"}:
        gap = _mean_gap(failing, values, _unit(name))
        if gap:
            block.append(gap)
        machines = _machine_sets(failing)
        if machines:
            block.append(machines)
    elif len(failing) == 1 and failing[0]["kind"] == "product":
        if len([cell for cell in failing[0]["machines"] if int(cell.get("n") or 0)]) >= 2:
            block.append("各机台都过限，排除某一台机。")
        if clear:
            block.append(f"{'、'.join(view['label'] for view in clear)}在限内，排除各批共用的上限。")
    elif len(failing) == 1 and failing[0]["kind"] == "machine":
        lead = failing[0]["lead"]
        for other in clear:
            found = next((cell for cell in other["machines"] if str(cell.get("name") or "") == lead), None)
            if found is None:
                block.append(f"{other['label']}没有 {lead}。")
            elif not _cell_fails(found):
                block.append(f"{other['label']}的 {lead} 没有超限，排除跟着产品走。")
    elif len(failing) == 1 and failing[0]["kind"] == "slots":
        hot_names = [str(cell.get("name") or "") for cell in failing[0]["hot"]]
        for other in clear:
            contrast = _slot_contrast(other, hot_names, values)
            if contrast:
                block.append(contrast)
    elif len(failing) >= 2 and {view["kind"] for view in failing} == {"machine"} and len({view["lead"] for view in failing}) > 1:
        block.append("两批不是同一台机，排除跟着产品走。" if len(failing) == 2 else "各批不是同一台机，排除跟着产品走。")
    for view in clear:
        block.append(_clear_fact(view, values))
    return _join(block)


def render_cross(run: "SummaryRun") -> str:
    page = run.results[0]["result"] if run.results else {}
    places: dict[str, dict] = {}
    for entry in run.results:
        result = entry.get("result") if isinstance(entry, dict) else None
        if isinstance(entry, dict) and entry.get("tool") == "place" and isinstance(result, dict) and result.get("item"):
            places[str(result["item"])] = result
    values: list = []
    exposed: list[str] = []
    risk: list[str] = []
    batches = [batch for batch in page.get("batches") or [] if isinstance(batch, dict)]
    labels = {str(batch.get("batch") or ""): _batch_label(index) for index, batch in enumerate(batches)}
    census = {str(item.get("batch") or ""): item for item in run.payload.get("census") or [] if isinstance(item, dict)}
    for batch in batches:
        name = str(batch.get("batch") or "")
        exposed.extend(_opening(batch, census.get(name), values, heading=f"{labels.get(name, name)} {name}", method=False))
    exposed.append("按同一项对齐。先看每一批超限落在整批、一台机还是几个槽，再只比这一项。")
    for batch in batches:
        name = str(batch.get("batch") or "")
        items = [item for item in batch.get("items") or [] if isinstance(item, dict) and item.get("item")]
        if not items:
            exposed.append(f"{labels.get(name, name)} {name} 没有取到卡限项，这次对不齐。")
    catalog: dict[str, list[tuple[dict, dict]]] = {}
    for batch in batches:
        for item in batch.get("items") or []:
            if isinstance(item, dict) and item.get("item"):
                catalog.setdefault(str(item["item"]), []).append((batch, item))
    for name in sorted((item for item, pairs in catalog.items() if any(_fail_count(one) for _, one in pairs)), key=item_sort_key):
        exposed.append(_cross_item(name, catalog[name], labels, places, run.rows, values))
    for batch in batches:
        name = str(batch.get("batch") or "")
        label = labels.get(name, name)
        items = [item for item in batch.get("items") or [] if isinstance(item, dict) and item.get("item")]
        for item in sorted(items, key=lambda entry: item_sort_key(str(entry.get("item") or ""))):
            if _fail_count(item):
                continue
            near = _near_line(item, values)
            if near:
                risk.append(f"{label} {near}")
        for note in _limit_note(items, values):
            risk.append(f"{label}：{note}")
    if values:
        run.results.append({"tool": "derived", "result": {"values": values}})
    return conclusion_text({"exposed": exposed, "risk": risk})


def _near_line(item: dict, values: list) -> str:
    name = str(item.get("item") or "")
    unit = _unit(name)
    high, low = item.get("high"), item.get("low")
    maximum, minimum, span = item.get("maximum"), item.get("minimum"), item.get("range")
    if all(isinstance(value, (int, float)) for value in (high, maximum, span)) and 0 <= high - maximum < span:
        return f"{name}：最大值 {_keep(values, maximum)}{unit} 贴近上限 {_keep(values, high)}{unit}，离上限的距离小于这一项的极差，所以写成贴近上限。"
    if all(isinstance(value, (int, float)) for value in (low, minimum, span)) and 0 <= minimum - low < span:
        return f"{name}：最小值 {_keep(values, minimum)}{unit} 贴近下限 {_keep(values, low)}{unit}，离下限的距离小于这一项的极差，所以写成贴近下限。"
    return ""


def conclusion_text(reply: dict) -> str:
    exposed = _clause_list(reply.get("exposed")) or ["这次没有已经超限的项。"]
    risk = _clause_list(reply.get("risk")) or ["没有潜在危险项。"]
    return json.dumps({"lines": [_EXPOSED, *exposed, _RISK, *risk]}, ensure_ascii=False)


def _clause_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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
        kept = [sentence for sentence in _sentences(line) if _line_ok(sentence, allowed, names)]
        if kept:
            lines.append(_explain(unify_words("".join(kept))))
    if not lines:
        raise AppError(502, "AGENT_FAILED", "总结里的数字和报告对不上")
    return polish_summary_lines(lines)


async def _post_summary(client: httpx.AsyncClient, body: dict) -> httpx.Response:
    return await client.post(
        chat_completions_url(settings.anthropic_base_url),
        headers={"Authorization": f"Bearer {settings.anthropic_api_key}"},
        json=body,
    )


def build_evidence(payload: dict, focus: list[str] | None = None) -> dict:
    chosen = set(focus or _default_focus(payload))
    batches = [item for item in payload.get("batches") or [] if isinstance(item, dict)]
    overall = payload.get("overall") if isinstance(payload.get("overall"), dict) else {}
    scope = [_batch_scope(item) for item in batches]
    small = any(item["n"] < 30 for item in scope)
    if small:
        chosen.discard("mean")
    if len(scope) < 2:
        chosen.discard("mean")
        chosen.discard("defect_rate")
    evidence: dict = {
        "mode": "multi" if len(scope) > 1 else "single",
        "tested": payload.get("tested"),
        "aborted": payload.get("aborted"),
        "batches": scope,
    }
    source = batches if len(batches) > 1 else [overall]
    if "over_limit" in chosen:
        evidence["over_limit"] = _over_limit(source)
    if "margin" in chosen:
        evidence["near_limit"] = _near_limit(source)
    if "spread" in chosen:
        evidence["spread"] = _spread(source if len(batches) > 1 else [overall])
    if "trend" in chosen:
        evidence["trend"] = _trends(source)
    if "defect_rate" in chosen and len(batches) > 1:
        evidence["defect_rate"] = _defect_rate(batches)
    if "mean" in chosen and len(batches) > 1:
        evidence["mean"] = _mean_compare(batches)
    return evidence


def _default_focus(payload: dict, mode: str = "cross") -> list[str]:
    batches = [item for item in payload.get("batches") or [] if isinstance(item, dict)]
    if mode == "single" or len(batches) < 2:
        return ["over_limit", "margin", "spread", "trend"]
    small = any(_batch_scope(item)["n"] < 30 for item in batches)
    if small:
        return ["defect_rate", "spread", "trend"]
    return ["defect_rate", "mean", "spread", "trend"]


def build_mode_evidence(payload: dict, mode: str, focus: list[str] | None = None) -> dict:
    batches = [item for item in payload.get("batches") or [] if isinstance(item, dict)]
    if mode == "cross":
        evidence = build_evidence(payload, focus)
        evidence["mode"] = "cross"
        return evidence
    chosen = [item for item in (focus or _default_focus(payload, "single")) if item not in {"mean", "defect_rate"}]
    sections = []
    for batch in batches:
        scope = _batch_scope(batch)
        one = {"tested": scope["n"], "aborted": batch.get("aborted") or 0, "overall": batch, "batches": [batch]}
        section = build_evidence(one, chosen)
        section["batch"] = batch.get("name") or ""
        if scope.get("piece"):
            section["piece"] = scope["piece"]
        sections.append(section)
    if not sections:
        sections.append(build_evidence(payload, chosen or _default_focus(payload, "single")))
    return {"mode": "single", "sections": sections}


def _batch_scope(slice_row: dict) -> dict:
    counts = [int(item.get("n") or 0) for item in slice_row.get("items") or [] if isinstance(item, dict)]
    failed = sum(int(item.get("count") or 0) for item in slice_row.get("fail_groups") or [] if isinstance(item, dict))
    count = max(counts) if counts else 0
    scope = {"batch": slice_row.get("name") or "", "n": count, "failed": failed, "aborted": slice_row.get("aborted") or 0}
    if count < 30:
        scope["piece"] = "不足片"
    return scope


def _items(slice_row: dict) -> list[dict]:
    return [item for item in slice_row.get("items") or [] if isinstance(item, dict)]


def _over_limit(slices: list[dict]) -> list[dict]:
    rows = []
    for slice_row in slices:
        for item in _items(slice_row):
            count = int(item.get("high_fail") or 0) + int(item.get("low_fail") or 0)
            if count:
                rows.append({"batch": slice_row.get("name") or "", "item": item.get("item"), "n": item.get("n"), "high_fail": item.get("high_fail"), "low_fail": item.get("low_fail"), "high": item.get("high"), "low": item.get("low")})
    rows.sort(key=lambda item: (-(int(item["high_fail"] or 0) + int(item["low_fail"] or 0)), str(item["item"])))
    return rows[:6]


def _near_limit(slices: list[dict]) -> list[dict]:
    rows = []
    for slice_row in slices:
        for item in _items(slice_row):
            margin = item.get("margin_high")
            if item.get("high_fail") or item.get("low_fail") or not isinstance(margin, (int, float)) or margin >= 0.3:
                continue
            rows.append({"batch": slice_row.get("name") or "", "item": item.get("item"), "n": item.get("n"), "mean": item.get("mean"), "margin_high": margin, "high": item.get("high")})
    rows.sort(key=lambda item: float(item["margin_high"]))
    return rows[:4]


def _spread(slices: list[dict]) -> list[dict]:
    if len(slices) < 2:
        ranked = sorted(_items(slices[0]) if slices else [], key=lambda item: float(item.get("range") or 0), reverse=True)
        top = next((item for item in ranked if item.get("range")), None)
        if top is None:
            return []
        span = _span(top)
        width = float(top["range"])
        if span is not None and width < 0.2 * span:
            return []
        if span is None and width < 1:
            return []
        return [{"batch": slices[0].get("name") or "", "item": top.get("item"), "n": top.get("n"), "range": top.get("range")}]
    names = sorted({item.get("item") for row in slices for item in _items(row) if item.get("item")})
    rows = []
    for name in names:
        found = []
        for slice_row in slices:
            item = next((one for one in _items(slice_row) if one.get("item") == name), None)
            if item and isinstance(item.get("range"), (int, float)) and int(item.get("n") or 0) >= 30:
                found.append(item | {"batch": slice_row.get("name") or ""})
        if len(found) < 2:
            continue
        ranges = [float(item["range"]) for item in found]
        if min(ranges) <= 0 or max(ranges) < 2 * min(ranges):
            continue
        rows.append({"item": name, "batches": [{"batch": item["batch"], "n": item.get("n"), "range": item.get("range")} for item in found]})
    return rows[:4]


def _trends(slices: list[dict]) -> list[dict]:
    rows = []
    for slice_row in slices:
        for item in _items(slice_row):
            trend = str(item.get("trend") or "")
            if trend in {"后半段升高", "后半段降低"}:
                rows.append({"batch": slice_row.get("name") or "", "item": item.get("item"), "n": item.get("n"), "trend": trend})
    return rows[:6]


def _defect_rate(batches: list[dict]) -> list[dict]:
    names = sorted({item.get("item") for row in batches for item in _items(row) if item.get("item")})
    rows = []
    for name in names:
        sides = []
        for slice_row in batches:
            item = next((one for one in _items(slice_row) if one.get("item") == name), None)
            if item is None:
                continue
            sides.append({"batch": slice_row.get("name") or "", "n": item.get("n"), "high_fail": item.get("high_fail"), "low_fail": item.get("low_fail")})
        if len(sides) < 2:
            continue
        fails = [int(item.get("high_fail") or 0) + int(item.get("low_fail") or 0) for item in sides]
        if len(set(fails)) < 2 and not any(fails):
            continue
        if any(fails):
            rows.append({"item": name, "batches": sides})
    rows.sort(key=lambda item: -max(int(side.get("high_fail") or 0) + int(side.get("low_fail") or 0) for side in item["batches"]))
    return rows[:6]


def _mean_compare(batches: list[dict]) -> list[dict]:
    names = sorted({item.get("item") for row in batches for item in _items(row) if item.get("item")})
    rows = []
    for index, left in enumerate(batches):
        for right in batches[index + 1:]:
            for name in names:
                one = next((item for item in _items(left) if item.get("item") == name), None)
                other = next((item for item in _items(right) if item.get("item") == name), None)
                compared = _welch_summary(one, other)
                if compared is None:
                    continue
                span = _span(one)
                gap = abs(float(compared["diff"]))
                practical = span is None or gap >= 0.1 * span
                if compared["p"] >= 0.05 and not practical:
                    continue
                rows.append({
                    "item": name,
                    "left": left.get("name") or "",
                    "right": right.get("name") or "",
                    "n_left": one.get("n") if one else 0,
                    "n_right": other.get("n") if other else 0,
                    "mean_left": compared["mean_left"],
                    "mean_right": compared["mean_right"],
                    "diff": round(gap, 3),
                    "p": compared["p"],
                    "practical": practical,
                })
    rows.sort(key=lambda item: -float(item["diff"]))
    return rows[:8]


def _welch_summary(left: dict | None, right: dict | None) -> dict | None:
    from app.service.reports.stats import student_t_sf

    if left is None or right is None:
        return None
    n_left, n_right = int(left.get("n") or 0), int(right.get("n") or 0)
    if n_left < 30 or n_right < 30:
        return None
    mean_left, mean_right = left.get("mean"), right.get("mean")
    std_left, std_right = left.get("std"), right.get("std")
    if not all(isinstance(item, (int, float)) for item in (mean_left, mean_right, std_left, std_right)):
        return None
    spread = float(std_left) ** 2 / n_left + float(std_right) ** 2 / n_right
    if spread == 0:
        probability = 0.0 if mean_left != mean_right else 1.0
    else:
        from app.service.reports.stats import _welch_df

        freedom = _welch_df(float(std_left) ** 2, n_left, float(std_right) ** 2, n_right, spread)
        probability = min(1.0, 2 * student_t_sf(abs(float(mean_left) - float(mean_right)) / math.sqrt(spread), freedom))
    shown = 0.001 if probability < 0.001 else round(probability, 3)
    return {"mean_left": mean_left, "mean_right": mean_right, "diff": float(mean_left) - float(mean_right), "p": shown}


def _span(item: dict | None) -> float | None:
    if item is None:
        return None
    high, low = item.get("high"), item.get("low")
    if isinstance(high, (int, float)) and isinstance(low, (int, float)) and high > low:
        return float(high) - float(low)
    return None


def analysis_brief(payload: dict, mode: str) -> dict:
    chosen = mode if mode in {"single", "cross"} else "single"
    batches = [item for item in payload.get("batches") or [] if isinstance(item, dict)]
    if chosen == "cross":
        if len(batches) < 2:
            raise AppError(400, "BAD_REQUEST", "只有一批，不能做跨批次分析")
        evidence = build_evidence(payload, _default_focus(payload, "cross"))
        return _cross_brief(evidence, batches)
    sections = []
    for batch in batches:
        scope = _batch_scope(batch)
        one = {"tested": scope["n"], "aborted": batch.get("aborted") or 0, "overall": batch, "batches": [batch]}
        section = build_evidence(one, _default_focus(one, "single"))
        section["batch"] = batch.get("name") or ""
        section["groups"] = _together(batch)
        if scope.get("piece"):
            section["piece"] = scope["piece"]
        sections.append(_section_brief(section))
    return {"mode": "single", "sections": sections}


def _together(batch: dict) -> list[list[str]]:
    groups = []
    for group in batch.get("fail_groups") or []:
        if not isinstance(group, dict):
            continue
        items = [str(item) for item in group.get("items") or []]
        if len(items) > 1:
            groups.append(items)
    return groups[:2]


def _section_brief(section: dict) -> dict:
    whole: list[str] = []
    partial: list[str] = []
    for row in section.get("over_limit") or []:
        count = int(row.get("n") or 0)
        failed = int(row.get("high_fail") or 0) + int(row.get("low_fail") or 0)
        name = str(row.get("item") or "")
        if not name or not failed:
            continue
        if count and failed / count >= 0.9:
            whole.append(name)
        else:
            partial.append(name)
    scope = (section.get("batches") or [{}])[0]
    brief: dict = {
        "batch": section.get("batch") or scope.get("batch") or "",
        "n": scope.get("n") or 0,
        "verdict": "只能看方向" if section.get("piece") else ("整批不过" if whole else ("一部分不过" if partial else "能过")),
        "whole": whole,
        "partial": partial,
        "together": section.get("groups") or [],
        "risk": [str(row.get("item")) for row in section.get("near_limit") or [] if row.get("item")],
        "drift": [f"{row.get('item')}{row.get('trend')}" for row in section.get("trend") or [] if row.get("item")],
    }
    if section.get("piece"):
        brief["piece"] = "不足片"
    return brief


def _cross_brief(evidence: dict, batches: list[dict]) -> dict:
    failed: dict[str, set[str]] = {}
    for row in evidence.get("defect_rate") or []:
        for side in row.get("batches") or []:
            name = str(side.get("batch") or "")
            if int(side.get("high_fail") or 0) + int(side.get("low_fail") or 0):
                failed.setdefault(name, set()).add(str(row.get("item") or ""))
    scopes = [_batch_scope(batch) for batch in batches]
    for scope in scopes:
        failed.setdefault(str(scope["batch"]), set())
    sets = list(failed.values())
    shared = set.intersection(*sets) if len(sets) > 1 else set()
    small = [scope["batch"] for scope in scopes if scope.get("piece") == "不足片"]
    mean_notes = []
    for row in evidence.get("mean") or []:
        higher = row["left"] if float(row["mean_left"]) >= float(row["mean_right"]) else row["right"]
        mean_notes.append({"item": row["item"], "higher": higher, "practical": bool(row["practical"])})
    only = {name: sorted(items - shared) for name, items in failed.items()}
    comparable = not small
    same = comparable and not any(only.values()) and not any(item["practical"] for item in mean_notes)
    return {
        "mode": "cross",
        "comparable": comparable,
        "same_level": same,
        "batches": scopes,
        "shared": sorted(shared),
        "only": only,
        "mean": mean_notes,
        "spread": [row.get("item") for row in evidence.get("spread") or [] if row.get("item")],
    }


def _slice_count(slice_row: dict) -> int:
    counts = [int(item.get("n") or 0) for item in _items(slice_row)]
    return max(counts) if counts else 0


def _same_limits(batches: list[dict]) -> bool:
    found: dict[str, set[tuple]] = {}
    for batch in batches:
        for item in _items(batch):
            if int(item.get("n") or 0) <= 0:
                continue
            found.setdefault(str(item.get("item") or ""), set()).add((item.get("low"), item.get("high")))
    shared = [pairs for pairs in found.values() if len(pairs) > 1]
    return all(len(pairs) == 1 for pairs in shared)


def _fail_names(batch: dict) -> tuple[list[str], list[str]]:
    whole: list[str] = []
    partial: list[str] = []
    for item in _items(batch):
        count = int(item.get("n") or 0)
        failed = int(item.get("high_fail") or 0) + int(item.get("low_fail") or 0)
        name = str(item.get("item") or "")
        if not name or not failed:
            continue
        if count and failed / count >= 0.9:
            whole.append(name)
        else:
            partial.append(name)
    return whole, partial


def _near_names(batch: dict) -> list[str]:
    names = []
    for item in _items(batch):
        margin = item.get("margin_high")
        if item.get("high_fail") or item.get("low_fail") or not isinstance(margin, (int, float)) or margin >= 0.3:
            continue
        name = str(item.get("item") or "")
        if name:
            names.append(name)
    return names


def _later(batch: dict) -> list[str]:
    rows = []
    for item in _items(batch):
        trend = str(item.get("trend") or "")
        name = str(item.get("item") or "")
        if name and trend in {"后半段升高", "后半段降低"}:
            rows.append(f"{name}{trend}")
    return rows


def _piece_row(batch: dict) -> dict:
    scope = _batch_scope(batch)
    whole, partial = _fail_names(batch)
    together = []
    failed = 0
    for group in batch.get("fail_groups") or []:
        if not isinstance(group, dict):
            continue
        failed += int(group.get("count") or 0)
        items = [str(item) for item in group.get("items") or [] if str(item)]
        if len(items) > 1:
            together.append({"count": int(group.get("count") or 0), "items": items})
    together.sort(key=lambda item: -int(item["count"]))
    failed_names = set(whole) | set(partial)
    later = _later(batch)
    exposed_later = [item for item in later if item.split("后半段")[0] in failed_names]
    risk_later = [item for item in later if item.split("后半段")[0] not in failed_names]
    exposed: dict = {}
    if whole:
        exposed["whole"] = whole
    if partial:
        exposed["partial"] = partial
    if together:
        exposed["together"] = together[:4]
    if exposed_later:
        exposed["later"] = exposed_later
    if not exposed:
        exposed = {"none": "没有已经超限的项"}
    risk: dict = {}
    near = _near_names(batch)
    if near:
        risk["near"] = near
    if risk_later:
        risk["later"] = risk_later
    if not risk:
        risk = {"none": "没有贴着上限、也没有后半段还在走的项"}
    row = {
        "batch": scope["batch"],
        "n": scope["n"],
        "passed": max(int(scope["n"]) - failed, 0),
        "exposed": exposed,
        "risk": risk,
    }
    if scope.get("piece"):
        row["piece"] = "不足片"
    return row


def tool_scale(payload: dict) -> dict:
    batches = [item for item in payload.get("batches") or [] if isinstance(item, dict)]
    rows = []
    for batch in batches:
        scope = _batch_scope(batch)
        row = {"batch": scope["batch"], "n": scope["n"], "aborted": int(batch.get("aborted") or 0), "invalid": int(batch.get("invalid") or 0)}
        if scope.get("piece"):
            row["piece"] = "不足片"
        rows.append(row)
    same = _same_limits(batches)
    return {"batches": rows, "limits": "上限是同一套" if same else "上限不是同一套"}


def tool_pieces(payload: dict) -> dict:
    batches = [item for item in payload.get("batches") or [] if isinstance(item, dict)]
    return {"batches": [_piece_row(batch) for batch in batches]}


def _fail_rate(slice_row: dict, name: str) -> float | None:
    item = next((one for one in _items(slice_row) if one.get("item") == name), None)
    if item is None:
        return None
    count = int(item.get("n") or 0)
    if not count:
        return None
    failed = int(item.get("high_fail") or 0) + int(item.get("low_fail") or 0)
    return failed / count


def _shows_problem(slice_row: dict, whole: list[str]) -> bool:
    if whole:
        rates = [_fail_rate(slice_row, name) for name in whole]
        known = [rate for rate in rates if rate is not None]
        return bool(known) and all(rate >= 0.9 for rate in known)
    return any(int(item.get("high_fail") or 0) + int(item.get("low_fail") or 0) for item in _items(slice_row))


def _ambient_notes(batches: list[dict]) -> list[dict]:
    notes = []
    for batch in batches:
        ambient = next((item for item in _items(batch) if item.get("item") == "室温"), None)
        fails = 0 if ambient is None else int(ambient.get("high_fail") or 0) + int(ambient.get("low_fail") or 0)
        if ambient is None or not fails:
            continue
        thermal_whole = 0
        thermal = set()
        for item in _items(batch):
            name = str(item.get("item") or "")
            failed = int(item.get("high_fail") or 0) + int(item.get("low_fail") or 0)
            count = int(item.get("n") or 0)
            if not name.startswith("Temp_") or not failed:
                continue
            thermal.add(name)
            if count and failed / count >= 0.9:
                thermal_whole = max(thermal_whole, failed)
        mixed = False
        for group in batch.get("fail_groups") or []:
            if not isinstance(group, dict):
                continue
            names = {str(item) for item in group.get("items") or []}
            if "室温" in names and names & thermal:
                mixed = True
        if thermal_whole and fails < 0.5 * thermal_whole:
            note = "室温只在一部分片子上，和整批温差分开看"
        elif not thermal:
            note = "室温另有片子超限"
        elif mixed:
            note = "室温和温差在同一批片子"
        else:
            note = "室温和温差不是同一批片子"
        notes.append({"batch": batch.get("name") or "", "note": note})
    return notes


def _batch_source(batch: dict, machines: list[dict], slots: list[dict]) -> dict:
    scope = _batch_scope(batch)
    if scope.get("piece") == "不足片":
        return {"batch": scope["batch"], "judgment": "不足片，不要用机台分布判断是板还是过程"}
    whole = _fail_names(batch)[0]
    machine_hit = [item for item in machines if _shows_problem(item, whole)]
    slot_hit = [item for item in slots if _shows_problem(item, whole)]
    where = ""
    if not whole:
        judgment = "没有整批超限的项"
    elif len(machines) >= 2 and len(machine_hit) == len(machines):
        judgment = "各机台都一样，更像这批均热板或这套上限"
    elif len(slots) >= 2 and len(slot_hit) == 1 and len(slots) > len(slot_hit):
        where = str(slot_hit[0].get("name") or "")
        judgment = "集中在一个槽位，更像测试过程"
    elif len(machines) >= 2 and len(machine_hit) == 1:
        where = str(machine_hit[0].get("name") or "")
        judgment = "集中在一台机，更像测试过程"
    elif len(machines) < 2:
        judgment = "机台分不开，不要据此判断是板还是过程"
    else:
        judgment = "机台之间不一样，不要写成各机台都一样"
    row = {"batch": scope["batch"], "judgment": judgment}
    if where:
        row["where"] = where
    return row


def tool_source(payload: dict) -> dict:
    batches = [item for item in payload.get("batches") or [] if isinstance(item, dict)]
    machines = [item for item in payload.get("machines") or [] if isinstance(item, dict) and item.get("name") and _slice_count(item) >= 30]
    slots = [item for item in payload.get("slots") or [] if isinstance(item, dict) and item.get("name") and _slice_count(item) >= 30]
    result = {
        "batches": [_batch_source(batch, machines, slots) for batch in batches],
        "aborted": int(payload.get("aborted") or 0),
        "invalid": int(payload.get("invalid") or 0),
        "discarded": int(payload.get("discarded") or 0),
    }
    if machines:
        result["machines"] = [str(item.get("name") or "") for item in machines]
        result["machine_count"] = len(machines)
    ambient = _ambient_notes(batches)
    if ambient:
        result["ambient"] = ambient
    return result


def tool_means(payload: dict, mode: str) -> dict:
    if mode != "cross":
        return {"refused": "单批次不比较均值"}
    batches = [item for item in payload.get("batches") or [] if isinstance(item, dict)]
    if len(batches) < 2:
        return {"refused": "只有一批，不能比较均值"}
    if any(_batch_scope(batch).get("piece") == "不足片" for batch in batches) or not _same_limits(batches):
        return {"refused": "有不足片或上限不是同一套，只写方向，不比谁更好"}
    items = []
    for row in _mean_compare(batches):
        higher = row["left"] if float(row["mean_left"]) >= float(row["mean_right"]) else row["right"]
        items.append({"item": row["item"], "higher": higher, "reaches_limit": bool(row["practical"])})
    return {"items": items}


def _item_names(rows: list[dict]) -> list[str]:
    return sorted({str(row.get("item") or "") for row in rows if row.get("item")}, key=item_sort_key)


def _match_item(name: str, rows: list[dict]) -> str | None:
    wanted = str(name or "").strip()
    names = _item_names(rows)
    if wanted in names:
        return wanted
    folded = {item.lower(): item for item in names}
    if wanted.lower() in folded:
        return folded[wanted.lower()]
    bare = re.sub(r"^temp_", "", wanted, flags=re.I)
    for item in names:
        if re.sub(r"^temp_", "", item, flags=re.I).lower() == bare.lower():
            return item
    return None


def _outside(row: dict) -> bool:
    value = row.get("value")
    high, low = row.get("high"), row.get("low")
    if not isinstance(value, (int, float)):
        return False
    if isinstance(high, (int, float)) and value > high:
        return True
    return isinstance(low, (int, float)) and value < low


def _gap(row: dict) -> float:
    value = float(row.get("value") or 0)
    gap = 0.0
    high, low = row.get("high"), row.get("low")
    if isinstance(high, (int, float)) and value > high:
        gap = max(gap, value - float(high))
    if isinstance(low, (int, float)) and value < low:
        gap = max(gap, float(low) - value)
    return gap


def _num(value: object) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = round(float(value), 3)
    if number == int(number):
        return int(number)
    return number


def _wafer(row: dict) -> dict:
    return {
        "serial": row.get("serial") or row.get("run_id") or "",
        "machine": row.get("machine_id") or "",
        "slot": row.get("slot_name") or "",
        "value": _num(row.get("value")),
        "outside": _outside(row),
    }


def _wafers_for(rows: list[dict], item: str) -> dict[str, list[dict]]:
    grouped: dict[str, dict[str, dict]] = {}
    for row in rows:
        if row.get("item") != item:
            continue
        batch = str(row.get("batch_id") or "")
        grouped.setdefault(batch, {})[str(row.get("run_id") or "")] = row
    return {batch: list(found.values()) for batch, found in grouped.items()}


def _pick_wafers(wafers: list[dict], item: str) -> tuple[list[dict], list[dict]]:
    over = [row for row in wafers if _outside(row)]
    over.sort(key=_gap, reverse=True)
    shown = over[:_FAIL_SHOWN]
    passed = [row for row in wafers if row.get("passed") is True and not _outside(row)]
    draw = min(_PASS_SAMPLE, len(passed))
    sample = random.Random(item).sample(passed, draw) if draw else []
    return shown, sample


def _slice_stats(payload: dict, batch: str, item: str) -> dict:
    found = next((one for one in payload.get("batches") or [] if isinstance(one, dict) and one.get("name") == batch), None)
    row = next((one for one in (found or {}).get("items") or [] if isinstance(one, dict) and one.get("item") == item), None)
    if not isinstance(row, dict):
        return {}
    stats = {
        "n": int(row.get("n") or 0),
        "mean": _num(row.get("mean")),
        "minimum": _num(row.get("minimum")),
        "maximum": _num(row.get("maximum")),
        "range": _num(row.get("range")),
        "low": _num(row.get("low")),
        "high": _num(row.get("high")),
        "high_fail": int(row.get("high_fail") or 0),
        "low_fail": int(row.get("low_fail") or 0),
    }
    if stats["n"] < 30:
        stats["piece"] = "不足片"
    return stats


def tool_results(payload: dict, rows: list[dict], item: str) -> dict:
    matched = _match_item(item, rows)
    names = _item_names(rows)
    if not matched:
        return {"error": "没有这一项", "items": names}
    batches = []
    for batch, wafers in _wafers_for(rows, matched).items():
        over, sample = _pick_wafers(wafers, f"{batch}:{matched}")
        block = {
            "batch": batch,
            **_slice_stats(payload, batch, matched),
            "over_count": sum(1 for row in wafers if _outside(row)),
            "over": [_wafer(row) for row in over],
            "pass_count": sum(1 for row in wafers if row.get("passed") is True),
            "pass_sample": [_wafer(row) for row in sample],
        }
        if block["over_count"] > len(block["over"]):
            block["over_listed"] = len(block["over"])
        batches.append(block)
    return {"item": matched, "batches": batches}


def _item_brief(item: dict) -> dict:
    return {
        "item": item.get("item") or "",
        "n": int(item.get("n") or 0),
        "mean": _num(item.get("mean")),
        "minimum": _num(item.get("minimum")),
        "maximum": _num(item.get("maximum")),
        "range": _num(item.get("range")),
        "low": _num(item.get("low")),
        "high": _num(item.get("high")),
        "high_fail": int(item.get("high_fail") or 0),
        "low_fail": int(item.get("low_fail") or 0),
    }


def tool_page(payload: dict, rows: list[dict]) -> dict:
    seen: dict[str, tuple[str, bool]] = {}
    for row in rows:
        run_id = str(row.get("run_id") or "")
        if run_id and run_id not in seen:
            seen[run_id] = (str(row.get("batch_id") or ""), row.get("passed") is True)
    counts: dict[str, list[int]] = {}
    for batch, passed in seen.values():
        cell = counts.setdefault(batch, [0, 0])
        cell[0] += 1
        if passed:
            cell[1] += 1
    batches = []
    for batch in payload.get("batches") or []:
        if not isinstance(batch, dict):
            continue
        name = str(batch.get("name") or "")
        tested, passed = counts.get(name, [0, 0])
        block = {
            "batch": name,
            "tested": tested,
            "passed": passed,
            "failed": tested - passed,
            "yield_rate": round(100 * passed / tested, 2) if tested else 0,
            "items": [_item_brief(item) for item in batch.get("items") or [] if isinstance(item, dict)],
        }
        if tested < 30:
            block["piece"] = "不足片"
        batches.append(block)
    return {"batches": batches}


def tool_place(rows: list[dict], item: str) -> dict:
    matched = _match_item(item, rows)
    if not matched:
        return {"error": "没有这一项", "items": _item_names(rows)}
    batches = []
    for batch, wafers in _wafers_for(rows, matched).items():
        machines: dict[str, dict] = {}
        slots: dict[str, dict] = {}
        for row in wafers:
            for bucket, key in ((machines, row.get("machine_id")), (slots, row.get("slot_name"))):
                name = str(key or "")
                cell = bucket.setdefault(name, {"name": name, "n": 0, "high_fail": 0, "low_fail": 0, "values": []})
                cell["n"] += 1
                value = row.get("value")
                high, low = row.get("high"), row.get("low")
                if isinstance(value, (int, float)):
                    cell["values"].append(float(value))
                if isinstance(value, (int, float)) and isinstance(high, (int, float)) and value > high:
                    cell["high_fail"] += 1
                elif isinstance(value, (int, float)) and isinstance(low, (int, float)) and value < low:
                    cell["low_fail"] += 1
        for bucket in (machines, slots):
            for cell in bucket.values():
                values = cell.pop("values")
                cell["minimum"] = _num(min(values)) if values else None
                cell["maximum"] = _num(max(values)) if values else None
                cell["mean"] = _num(sum(values) / len(values)) if values else None
        batches.append({
            "batch": batch,
            "machines": sorted(machines.values(), key=lambda one: (-one["high_fail"] - one["low_fail"], one["name"])),
            "slots": sorted(slots.values(), key=lambda one: (-one["high_fail"] - one["low_fail"], one["name"])),
        })
    return {"item": matched, "batches": batches}


def _curve(key: str, points: list[dict], low: float | None, high: float | None) -> dict:
    fields = _SAMPLE[key]
    ordered = sorted(points, key=lambda item: float(item.get("t_s") or 0))
    series = []
    for point in ordered:
        if len(fields) == 1:
            raw = point.get(fields[0])
            if usable(raw):
                series.append({"t_s": _num(point.get("t_s")), "value": _num(raw)})
        else:
            left, right = point.get(fields[0]), point.get(fields[1])
            if usable(left) and usable(right):
                series.append({"t_s": _num(point.get("t_s")), "value": _num(float(left) - float(right))})
    values = [float(item["value"]) for item in series if isinstance(item.get("value"), (int, float))]
    shape = process_shape(values, low, high)
    if len(series) > 6:
        step = max(len(series) // 5, 1)
        shortened = series[::step][:5]
        if shortened[-1] != series[-1]:
            shortened.append(series[-1])
        series = shortened
    return {"shape": shape, "points": series}


async def tool_process(session, rows: list[dict], item: str, serials: list[str]) -> dict:
    matched = _match_item(item, rows)
    if not matched:
        return {"error": "没有这一项", "items": _item_names(rows)}
    grouped = _wafers_for(rows, matched)
    chosen: list[dict] = []
    if serials:
        wanted = {str(one) for one in serials}
        for wafers in grouped.values():
            chosen.extend(row for row in wafers if str(row.get("serial") or "") in wanted or str(row.get("run_id") or "") in wanted)
        chosen = chosen[:_FAIL_SHOWN + _PASS_SAMPLE]
    else:
        for batch, wafers in grouped.items():
            failed, sample = _pick_wafers(wafers, f"{batch}:{matched}")
            chosen.extend(failed)
            chosen.extend(sample)
    key = next((str(row.get("key") or "") for row in chosen if row.get("key")), "")
    if key not in _SAMPLE:
        return {
            "item": matched,
            "note": "过程采样只保存了 T0、T1、室温、功率和由它们算出的 T0-T1。这一项只有最终结果，没有过程曲线。",
            "serials": [row.get("serial") or row.get("run_id") for row in chosen],
        }
    if session is None or not chosen:
        return {"item": matched, "note": "这几片没有过程采样", "serials": [row.get("serial") or "" for row in chosen]}
    ids = [str(row.get("run_id") or "") for row in chosen if row.get("run_id")]
    found = await session.scalars(select(RunSampleOrm).where(RunSampleOrm.run_id.in_(ids)))
    points: dict[str, list[dict]] = {}
    for point in found:
        points.setdefault(point.run_id, []).append({"t_s": point.t_s, "t0": point.t0, "t1": point.t1, "ta": point.ta, "power_w": point.power_w})
    curves = []
    for row in chosen:
        run_id = str(row.get("run_id") or "")
        curve = _curve(key, points.get(run_id, []), row.get("low"), row.get("high"))
        curve.update({"serial": row.get("serial") or run_id, "batch": row.get("batch_id") or "", "machine": row.get("machine_id") or "", "slot": row.get("slot_name") or ""})
        curves.append(curve)
    return {"item": matched, "curves": curves}


class SummaryRun:
    def __init__(self, payload: dict, mode: str, rows: list[dict] | None = None, session=None):
        self.payload = payload
        self.rows = rows or []
        self.session = session
        self.mode = mode if mode in {"single", "cross"} else "single"
        self.called: list[str] = []
        self.results: list[dict] = [{"tool": "page", "result": tool_page(self.payload, self.rows)}]
        self.called.append("page")
        self.placed: set[str] = set()
        self.ready = True

    def opening(self) -> str:
        page = self.results[0]["result"]
        return json.dumps({"mode": self.mode, "tools": ["place", "results", "process"], "page": page}, ensure_ascii=False)

    def looked_text(self) -> str:
        labels = []
        for name in self.called:
            label = _TOOL_LABEL.get(name)
            if label and label not in labels:
                labels.append(label)
        return f"查了{'、'.join(labels)}" if labels else ""

    async def turn(self, reply: dict) -> dict:
        tool = str(reply.get("tool") or "").strip()
        if tool:
            if self.mode in {"single", "cross"}:
                missing = self._unplaced()
                if missing and tool != "place":
                    return {"error": "先查这些超限项的机台和槽位", "items": missing}
                if not missing:
                    return {"error": "机台和槽位已经齐了，按句式写结论", "need": ["exposed", "risk"]}
                matched = _match_item(str(reply.get("item") or ""), self.rows)
                if matched in self.placed:
                    return {"error": "这一项已经查过", "items": missing}
            return await self._call(tool, reply)
        if isinstance(reply.get("exposed"), list) or isinstance(reply.get("risk"), list):
            if not self.ready:
                return {"error": "先查结果数据", "need": ["results"], "items": _item_names(self.rows)}
            missing = self._unplaced()
            if missing:
                return {"error": "这些超限项还没查机台和槽位", "items": missing}
            return {"done": True}
        return {"error": "返回 tool，或 exposed 和 risk"}

    def _unplaced(self) -> list[str]:
        if self.mode not in {"single", "cross"}:
            return []
        counts: dict[str, int] = {}
        page = self.results[0]["result"] if self.results else {}
        for batch in page.get("batches") or []:
            if not isinstance(batch, dict):
                continue
            for item in batch.get("items") or []:
                if not isinstance(item, dict):
                    continue
                fails = int(item.get("high_fail") or 0) + int(item.get("low_fail") or 0)
                name = str(item.get("item") or "")
                if fails and name:
                    counts[name] = max(counts.get(name, 0), fails)
        needed = sorted(counts, key=lambda name: (-counts[name], name))
        return [name for name in needed if name not in self.placed]

    async def _call(self, tool: str, reply: dict) -> dict:
        if tool not in _TOOL_LABEL or tool == "page":
            return {"error": "没有这项查询", "tools": ["place", "results", "process"]}
        item = str(reply.get("item") or "")
        if tool == "place":
            result = tool_place(self.rows, item)
            matched = str(result.get("item") or "")
            if matched:
                self.placed.add(matched)
        elif tool == "results":
            result = tool_results(self.payload, self.rows, item)
        else:
            serials = reply.get("serials") if isinstance(reply.get("serials"), list) else []
            result = await tool_process(self.session, self.rows, item, [str(one) for one in serials])
        self.called.append(tool)
        self.results.append({"tool": tool, "item": item, "result": result})
        return result


async def fill_template(run: SummaryRun) -> None:
    for name in list(run._unplaced()):
        await run.turn({"tool": "place", "item": name})


async def request_expert_summary(payload: dict, model: str | None = None, mode: str = "single", rows: list[dict] | None = None, session=None) -> tuple[str, dict, int, int, str]:
    run = SummaryRun(payload, mode, rows, session)
    if run.mode in {"single", "cross"}:
        await fill_template(run)
        rendered = render_single(run) if run.mode == "single" else render_cross(run)
        return rendered, {"results": run.results, "looked": run.looked_text()}, 0, 0, model or ""
    transcript = [_ASK, run.opening()]
    total_in = 0
    total_out = 0
    model_name = model or ""
    for _ in range(8):
        text, step_in, step_out, model_name = await _complete(model, "\n".join(transcript))
        total_in += step_in
        total_out += step_out
        try:
            reply = _object(text)
        except AppError:
            transcript.append("返回一个 json。")
            continue
        outcome = await run.turn(reply)
        if run.mode in {"single", "cross"} and run.placed and not run._unplaced():
            rendered = render_single(run) if run.mode == "single" else render_cross(run)
            return rendered, {"results": run.results, "looked": run.looked_text()}, total_in, total_out, model_name
        if outcome.get("done"):
            return conclusion_text(reply), {"results": run.results, "looked": run.looked_text()}, total_in, total_out, model_name
        transcript.append(json.dumps({"asked": reply.get("tool"), "result": outcome}, ensure_ascii=False))
    raise AppError(502, "AGENT_FAILED", "没有查到数据，结论没有生成")


def _focus_payload(scope: dict) -> dict:
    return {"batches": [{"name": item.get("batch"), "items": [{"n": item.get("n") or 0}]} for item in scope.get("batches") or []]}


async def _focus(scope: dict, model: str | None, mode: str = "cross") -> tuple[list[str], int, int]:
    fallback = _default_focus(_focus_payload(scope), mode)
    try:
        text, plan_in, plan_out, _ = await _complete(model, _PLAN + json.dumps(scope, ensure_ascii=False))
        raw = _object(text).get("focus")
    except AppError as exc:
        if exc.status == 503:
            raise
        return fallback, 0, 0
    if not isinstance(raw, list):
        return fallback, plan_in, plan_out
    allowed = {"over_limit", "margin", "spread", "trend", "mean", "defect_rate"}
    chosen = [str(item) for item in raw if str(item) in allowed]
    return (chosen or fallback), plan_in, plan_out


async def request_summary(payload: dict, model: str | None = None) -> tuple[str, int, int, str]:
    if not settings.anthropic_base_url or not settings.anthropic_api_key:
        raise AppError(503, "MODEL_NOT_CONFIGURED", "没有配置第三方模型地址或密钥")
    return await _complete(model, _ASK + json.dumps(payload, ensure_ascii=False))


async def _complete(model: str | None, content: str) -> tuple[str, int, int, str]:
    if not settings.anthropic_base_url or not settings.anthropic_api_key:
        raise AppError(503, "MODEL_NOT_CONFIGURED", "没有配置第三方模型地址或密钥")
    model = (model or settings.anthropic_model or "deepseek-flash").strip()
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
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
    if any(line in {_EXPOSED, _RISK} for line in polished):
        return polished
    if any(len(line) > 80 or len(_ITEM.findall(line)) > 1 for line in polished):
        return polished
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

    return re.sub(r"(?<!超)(上限裕量|下限裕量|均值|极差|最大值|最小值|上限|下限)\s*(-?\d+(?:\.\d+)?)(?![\d.])(?!\s*(?:℃|W|片))", place, line)


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


def _sentences(line: str) -> list[str]:
    parts = re.split(r"(?<=[。！？])", line)
    return [part.strip() for part in parts if part.strip()]


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
