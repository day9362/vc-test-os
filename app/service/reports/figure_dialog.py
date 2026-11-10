"""自由输入的追问、目录和切数据。预设按钮不走这里。"""

import json
import re

MAX_RUNS = 200
PROCESS_COLUMNS = [
    "t_s",
    *[f"temp_t{index}" for index in range(15)],
    "temp_ambient",
    "delta_t0_t1",
    *[f"delta_t1_t{index}" for index in range(2, 15)],
    *[f"force_{index}" for index in range(1, 15)],
    "power_w",
]

_PROMPT = """你是批次报告的画图分析员。用户用自然语言说明要什么图。每一轮只做一件事：信息不够就追问，信息够了就写 Python。

可以画的类型只有：柱状图、散点图、纺锤图、折线、箱线、热力图、超限片数。纺锤图的 type 是 spindle，每一组 data 是 [最小值, 均值, 最大值]。箱线 type 是 boxplot，柱状图是 bar，散点是 scatter，折线是 line，热力图是 heatmap，超限片数是 pareto。

数据有两包，用 run_id 相连。沙箱里的文件只包含这次确定的测试和列，不是整批。
results 是每条测试结束时的一行，列有 run_id、batch_id、machine_id、slot_index、serial_number、status、passed、fail_items、ended_at、ambient、deltas。deltas 是文本，每项带 item、value、low、high、limited。
samples 是过程采样。列与过程导出相同：t_s（秒），temp_t0 到 temp_t14、temp_ambient（℃），delta_t0_t1 和 delta_t1_t2 到 delta_t1_t14（℃），force_1 到 force_14（g），power_w（W），以及 run_id。没有 T_air、电机温度和 60 秒快照。

用代码读取传入的 results 和 samples，不要自己打开文件，不要打印整表。图上只返回算好的序列。定义 analyze(results, samples)，返回 dict，包含 title、panels、table。table 与图用同一段计算，包含 name、columns、rows。name 按所用数据起。
panels 最多 4 个。每个 panel 写 value_name、unit 和 scope。value_name 说明格子或点上的数是什么，例如均值、单片、片数、最小值。unit 用 ℃、W、片、g、s 或 %。scope 写整批、分机台、分机台槽或分批次，要和这张图实际的分法一致。数值保留两位小数。分类图要有 categories 和 series。散点的 series[].data 是 [[x, y], ...]。热力图要有 x_labels、y_labels、data，data 是 [[x下标, y下标, 值], ...]。热力图 y_labels 写机台，x_labels 写槽位，title 和 series_name 写项名。需要参考线时写 marks: [{"name": "上限", "y": 3}]。
上下限：用户明确给出了上下限，画图用用户规定的上下限；用户没提供就用目录里的方案限值。表名注明用的是哪一套。
一共追问三轮，三轮内把画这张图还缺的问题问完。每一轮最多 3 个问题。每个问题的选项写全，目录里用得上的机台、槽位、序列号、列名和限值都列上，不要只留前几个。
用户答完第三轮之后必须出图，不要再追问。还没问到的，按用户已经说过的做；用户没说过的，用目录里的方案限值和实际分组，自己定下来再画。
选中的测试超过 200 条时，在这三轮里问清要保留的机台、槽位或序列号，并在 slice 里写上。用户答完第三轮仍然超过 200 条，就按用户指定的范围取前 200 条出图，标题写明。
缺了就画不成时再追问，只限这三轮。问什么由这一张图还缺的信息决定。每个问题带选项。画图的类型优先询问用户，如果用户不提供图的类型则在数据和坐标确定后由你自己选。已经能确定画法时直接写代码。
均值、最小值、最大值、极差是额外项。这张图里还没有这四项时，才问要不要加上。已经决定要用，就直接标上，不要再问。
返回 json。追问时用 questions，每项是 text 和 options，并给 hint。hint.need 写这一轮至少还要用户给出什么，标注必须要给的信息否则不给就画不成。hint.allow 只写你还没定、用户可以自己规定的事，例如图的类型、横轴、纵轴、要不要标均值。已经决定的不要写进 allow。出图时用 code、title，并用 slice 写出 machines、slots、serials、columns、full_curve。columns 用目录里的列名。full_curve 为 true 只在用户要某一条完整过程曲线时使用。
不要使用 os、subprocess、socket，不要联网。
"""


def catalog_text(records: list[dict]) -> str:
    batches: dict[str, int] = {}
    machines: set[str] = set()
    slots: set[int] = set()
    serials: set[str] = set()
    items: dict[str, tuple] = {}
    passed = 0
    failed = 0
    fail_names: set[str] = set()
    for record in records:
        batch = str(record.get("batch_id") or "")
        if batch:
            batches[batch] = batches.get(batch, 0) + 1
        machine = str(record.get("machine_id") or "")
        if machine:
            machines.add(machine)
        slot = record.get("slot_index")
        if isinstance(slot, int) and not isinstance(slot, bool):
            slots.add(slot)
        serial = str(record.get("serial_number") or "")
        if serial:
            serials.add(serial)
        if record.get("passed") is True:
            passed += 1
        elif record.get("passed") is False:
            failed += 1
        for name in str(record.get("fail_items") or "").split("、"):
            if name.strip():
                fail_names.add(name.strip())
        for item in record.get("deltas") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("item") or "")
            if not label or label in items:
                continue
            items[label] = (item.get("low"), item.get("high"), item.get("limited") is not False)
    lines = [
        f"测试 {len(records)} 条，合格 {passed}，不合格 {failed}。",
        "批次：" + "，".join(f"{name} {count} 条" for name, count in sorted(batches.items())) if batches else "批次：无",
        "机台：" + "、".join(sorted(machines)) if machines else "机台：无",
        "槽：" + "、".join(str(item) for item in sorted(slots)) if slots else "槽：无",
        f"序列号 {len(serials)} 个。",
        "过程列：" + "、".join(PROCESS_COLUMNS),
        "方案上下限：" + ("；".join(_limit_text(name, spec) for name, spec in items.items()) if items else "无"),
        "不合格项：" + ("、".join(sorted(fail_names)) if fail_names else "无"),
        f"结果样例 {min(3, len(records))} 行，不是全部：{json.dumps(records[:3], ensure_ascii=False)}",
    ]
    return "\n".join(lines)


def parse_model_payload(text: str) -> dict:
    raw = (text or "").strip()
    start = raw.find("{")
    if start < 0:
        raise ValueError("模型没有返回 json")
    data, _ = json.JSONDecoder().raw_decode(raw[start:])
    if not isinstance(data, dict):
        raise ValueError("模型没有返回 json")
    code = _code(data.get("code"))
    questions = _questions(data.get("questions"))
    if code and "def analyze" in code:
        return {
            "kind": "draw",
            "code": code[:12000],
            "title": str(data.get("title") or "").strip()[:40],
            "slice": _slice(data.get("slice")),
        }
    note = str(data.get("note") or data.get("gap") or "").strip()
    if questions:
        return {"kind": "ask", "questions": questions[:3], "hint": _hint(data.get("hint"), questions[:3])}
    if note:
        return {"kind": "gap", "note": note[:300]}
    raise ValueError("模型没有返回问题或代码")


def filter_records(records: list[dict], spec: dict | None) -> list[dict]:
    chosen = spec or {}
    machines = {str(item) for item in chosen.get("machines") or []}
    slots = {int(item) for item in chosen.get("slots") or [] if _is_int(item)}
    serials = {str(item) for item in chosen.get("serials") or []}
    found = []
    for record in records:
        if machines and str(record.get("machine_id") or "") not in machines:
            continue
        slot = record.get("slot_index")
        if slots and slot not in slots:
            continue
        if serials and str(record.get("serial_number") or "") not in serials:
            continue
        found.append(record)
    return found


def too_many(records: list[dict]) -> bool:
    return len(records) > MAX_RUNS


def narrow_question(records: list[dict]) -> dict:
    machines = sorted({str(item.get("machine_id") or "") for item in records if item.get("machine_id")})
    slots = sorted({int(item["slot_index"]) for item in records if isinstance(item.get("slot_index"), int)})
    options = machines + [f"槽{slot}" for slot in slots]
    return {
        "text": f"这批有 {len(records)} 条测试，一次最多画 200 条。要保留哪些机台或槽位？",
        "options": options[:40],
    }


def thin_points(points: list[dict], full_curve: bool, limit: int = 180) -> list[dict]:
    if full_curve or len(points) <= limit:
        return points
    grouped: dict[str, list[dict]] = {}
    for point in points:
        grouped.setdefault(str(point.get("run_id") or ""), []).append(point)
    kept: list[dict] = []
    for rows in grouped.values():
        if len(rows) <= limit:
            kept.extend(rows)
            continue
        step = max(len(rows) // limit, 1)
        kept.extend(rows[::step][:limit])
    return kept


def keep_columns(points: list[dict], columns: list[str]) -> list[dict]:
    wanted = {"run_id", "t_s", *[item for item in columns if item in PROCESS_COLUMNS]}
    if len(wanted) <= 2:
        return points
    return [{key: value for key, value in point.items() if key in wanted} for point in points]


def _limit_text(name: str, spec: tuple) -> str:
    low, high, limited = spec
    if not limited or (low is None and high is None):
        return f"{name} 没有上下限"
    return f"{name} {low} 到 {high}"


_OPEN = (
    ("图的类型", r"类型|柱状|散点|箱线|折线|热力|纺锤|超限"),
    ("横轴", r"横轴|横坐标"),
    ("纵轴", r"纵轴|纵坐标"),
    ("均值、最小值、最大值、极差", r"均值|最小值|最大值|极差"),
)


def _hint(raw: object, questions: list[dict]) -> dict:
    given = raw if isinstance(raw, dict) else {}
    need = str(given.get("need") or "").strip()
    if not need:
        need = "；".join(item["text"].rstrip("？?") for item in questions)
    blob = need + " " + " ".join(item["text"] for item in questions)
    if "allow" in given:
        allow = str(given.get("allow") or "").strip()
    else:
        allow = "、".join(label for label, pattern in _OPEN if not re.search(pattern, blob))
    return {"need": need[:120], "allow": allow[:120]}


def _questions(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    found = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            found.append({"text": item.strip()[:80], "options": []})
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("question") or "").strip()
        if not text:
            continue
        options = []
        for option in item.get("options") or []:
            label = str(option).strip()
            if label and label not in options:
                options.append(label[:40])
        found.append({"text": text[:80], "options": options[:40]})
    return found


def _slice(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {"machines": [], "slots": [], "serials": [], "columns": [], "full_curve": False}
    return {
        "machines": [str(item) for item in raw.get("machines") or [] if str(item).strip()],
        "slots": [int(item) for item in raw.get("slots") or [] if _is_int(item)],
        "serials": [str(item) for item in raw.get("serials") or [] if str(item).strip()],
        "columns": [str(item) for item in raw.get("columns") or [] if str(item).strip()],
        "full_curve": raw.get("full_curve") is True,
    }


def _code(raw: object) -> str:
    code = str(raw or "")
    fenced = re.search(r"```(?:python)?\s*(.*?)```", code, re.S)
    if fenced:
        code = fenced.group(1)
    return code.strip()


def _is_int(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and value.isdigit()
