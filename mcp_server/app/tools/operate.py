import random
from typing import Literal

from app.approval import Preview, guarded, pick
from app.result import bad, fail, from_reply, missing, ok
from app.state import Ctx, ctx
from app.text import join_ids, phase_text, status_text

OperateAction = Literal[
    "power_on",
    "power_off",
    "reset",
    "maintenance",
    "slot_load",
    "slot_start",
    "slot_test",
    "slot_abort",
    "slot_clear_error",
    "create_batch",
    "production_precheck",
    "production_start",
    "production_stop",
    "sim_speed",
    "sim_scenario",
    "sim_fault",
    "requeue",
]

MACHINE_ACTIONS = {"power_on": "power-on", "power_off": "power-off", "reset": "reset", "maintenance": "maintenance"}


async def vc_operate(
    action: OperateAction,
    machine_ids: list[str] | None = None,
    machine_id: str | None = None,
    slot_index: int | None = None,
    serial_number: str | None = None,
    on: bool | None = None,
    model: str | None = None,
    count: int | None = None,
    defect_ratio: float | None = None,
    batch_factor: float | None = None,
    yield_rate: float | None = None,
    yield_random: bool | None = None,
    yield_min: float | None = None,
    yield_max: float | None = None,
    count_random: bool | None = None,
    count_min: int | None = None,
    count_max: int | None = None,
    plan_id: str | None = None,
    plan_version: int | None = None,
    batch_id: str | None = None,
    serial_numbers: list[str] | None = None,
    auto_recover: bool | None = None,
    max_count: int | None = None,
    speed: float | None = None,
    name: str | None = None,
    kind: str | None = None,
    confirm_id: str | None = None,
    approval: str | None = None,
) -> dict:
    """VC-TestOS 设备与生产操作（写）。中、高风险操作会先返回 APPROVAL_REQUIRED，由用户在页面批准后才执行；不要自己重复调用。

    机台：
    - power_on：上电，要 machine_ids。需批准。
    - power_off：关机，正在测试的槽会被中止，要 machine_ids。需批准。
    - reset：清故障复位；machine_ids 为空表示全部在线机台。需批准。
    - maintenance：进入（on=true）或退出（on=false）维修模式，要 machine_ids。需批准。
    单槽（slot_index 从 1 开始）：
    - slot_load：把板 serial_number 装到 machine_id 的 slot_index 号槽，不开测。需批准。
    - slot_start：对已装板的槽开测，返回 run_id。需批准。
    - slot_test：装板并立即开测，返回 run_id。需批准。
    - slot_abort：中止该槽并松开板。需批准。
    - slot_clear_error：清除该槽的错误。需批准。
    - requeue：把已测完的标准样品 serial_number 放回待测。普通板会被拒绝。需批准。
    生产：
    - create_batch：生成一批待测板，要 model。片数用 count，或 count_random 配 count_min、count_max。良率用 yield_rate（0 到 1，1 表示没有次品），或 yield_random 配 yield_min、yield_max；也可以直接给 defect_ratio。序列号由平台分配。需批准。
    - production_precheck：只做下发前检查，参数同 production_start。直接执行。
    - production_start：开始连续生产，要 machine_ids、plan_id、plan_version，batch_id 和 serial_numbers 二选一，可给 auto_recover、max_count。auto_recover 不填表示故障时停住。会先自动预检。需批准。
    - production_stop：停止连续生产；不给 batch_id 时停止当前生产。需批准。
    仿真（仅仿真数据源，只在用户明确要求时调用）：
    - sim_speed：改仿真倍率 speed，必须给出 machine_ids，不会改全部机台。只缩短等待，不改变温度曲线。需批准。
    - sim_scenario：对 machine_id 应用场景 name。需批准。先用 vc_data sim_catalog 查 name。
    - sim_fault：对 machine_id 注入故障 kind，可给 slot_index。需批准。先用 vc_data sim_catalog 查 kind。
    读数里 99999 和 9999 表示接触不良，-1 表示采集无应答，-2 表示回答无法解析。开测后用 vc_data 看进度，不要等测试结束。同意一次只覆盖这一次。
    confirm_id、approval 只由页面批准后使用，不要自己填写。
    """
    c = ctx()
    args = pick(
        {
            "machine_ids": machine_ids,
            "machine_id": machine_id,
            "slot_index": slot_index,
            "serial_number": serial_number,
            "on": on,
            "model": model,
            "count": count,
            "defect_ratio": defect_ratio,
            "batch_factor": batch_factor,
            "yield_rate": yield_rate,
            "yield_random": yield_random,
            "yield_min": yield_min,
            "yield_max": yield_max,
            "count_random": count_random,
            "count_min": count_min,
            "count_max": count_max,
            "plan_id": plan_id,
            "plan_version": plan_version,
            "batch_id": batch_id,
            "serial_numbers": serial_numbers,
            "auto_recover": auto_recover,
            "max_count": max_count,
            "speed": speed,
            "name": name,
            "kind": kind,
        }
    )

    async def preview():
        return await _preview(c, action, args)

    async def execute(values: dict, idem: str | None) -> dict:
        return await _run(c, action, values, idem)

    return await guarded(c, "vc_operate", action, args, confirm_id=confirm_id, approval=approval, preview=preview, execute=execute)


# ---------- 批准前检查 ----------


async def _machines(c: Ctx) -> dict[str, dict] | dict:
    reply = await c.get("/machines")
    if not reply.ok:
        return {"__error__": from_reply(reply)}
    return {row["machine_id"]: row for row in reply.body or [] if isinstance(row, dict) and row.get("machine_id")}


def _targets(args: dict) -> list[str]:
    ids = list(args.get("machine_ids") or [])
    if not ids and args.get("machine_id"):
        ids = [args["machine_id"]]
    return ids


def _unknown(ids: list[str], fleet: dict) -> dict | None:
    missing_ids = [item for item in ids if item not in fleet]
    if missing_ids:
        return fail(f"没有这些机台：{join_ids(missing_ids)}。", "NOT_FOUND", status=404, hints=["用 vc_line machines 查看机台编号"])
    return None


async def _preview(c: Ctx, action: str, args: dict):
    if action in MACHINE_ACTIONS:
        return await _machine_preview(c, action, args)
    if action.startswith("slot_"):
        return await _slot_preview(c, action, args)
    if action == "production_start":
        return await _start_preview(c, args)
    if action == "production_stop":
        return await _stop_preview(c, args)
    if action == "create_batch":
        return await _batch_preview(c, args)
    if action == "requeue":
        return await _requeue_preview(c, args)
    if action == "sim_speed":
        if not args.get("machine_ids"):
            return missing("machine_ids")
        if not args.get("speed") or args["speed"] <= 0:
            return bad("speed 必须大于 0。")
        return Preview(
            f"把 {join_ids(args['machine_ids'])} 的仿真倍率改为 {args['speed']}",
            ["只缩短步骤之间的等待，温度计算结果不变"],
        )
    if action == "sim_scenario":
        if not args.get("name") or not args.get("machine_id"):
            return await _need_catalog(c, "sim_scenario 要 name 和 machine_id。")
        return Preview(f"对 {args['machine_id']} 应用仿真场景「{args['name']}」", ["该机台的仿真参数会被场景覆盖"])
    if action == "sim_fault":
        if not args.get("kind") or not args.get("machine_id"):
            return await _need_catalog(c, "sim_fault 要 kind 和 machine_id。")
        where = f"{args['machine_id']} 的 {args['slot_index']} 号槽" if args.get("slot_index") else args["machine_id"]
        return Preview(f"给 {where} 注入故障 {args['kind']}", ["会产生告警，正在进行的测试可能失败"])
    return missing("action")


async def _machine_preview(c: Ctx, action: str, args: dict):
    fleet = await _machines(c)
    if "__error__" in fleet:
        return fleet["__error__"]
    ids = _targets(args)
    if action == "reset" and not ids:
        ids = [mid for mid, row in fleet.items() if row.get("comm_status") != "DISCONNECTED"]
        if not ids:
            return fail("现在没有可复位的在线机台。", "CONFLICT", status=409)
    if not ids:
        return missing("machine_ids")
    if (problem := _unknown(ids, fleet)) is not None:
        return problem
    if action == "maintenance" and args.get("on") is None:
        return missing("on")
    effects: list[str] = []
    for mid in ids:
        row = fleet[mid]
        if row.get("comm_status") == "DISCONNECTED":
            effects.append(f"{mid} 通信断开，这台会失败")
        sampling = [slot.get("index") for slot in row.get("slots") or [] if slot.get("phase") == "SAMPLING"]
        if action in {"power_off"} or (action == "maintenance" and args.get("on")):
            if sampling:
                effects.append(f"{mid} 的 {join_ids([str(i) for i in sampling])} 号槽正在测试，将被中止")
        if action == "power_on" and row.get("status") in {"FAULT", "MAINTENANCE"}:
            effects.append(f"{mid} {status_text(row.get('status'))}，上电会被拒绝")
        if action == "reset" and row.get("status") == "FAULT":
            effects.append(f"{mid} 故障：{row.get('alarm') or '未注明'}，复位后清除")
    verb = {
        "power_on": "上电",
        "power_off": "关机",
        "reset": "复位并清除故障",
        "maintenance": "进入维修模式" if args.get("on") else "退出维修模式",
    }[action]
    stored = {**{k: v for k, v in args.items() if k != "machine_id"}, "machine_ids": ids}
    return Preview(f"给 {join_ids(ids)} {verb}", effects, args=stored)


async def _slot_preview(c: Ctx, action: str, args: dict):
    mid, index = args.get("machine_id"), args.get("slot_index")
    if not mid or index is None:
        return missing("machine_id", "slot_index")
    if action in {"slot_load", "slot_test"} and not args.get("serial_number"):
        return missing("serial_number")
    reply = await c.get(f"/machines/{mid}")
    if not reply.ok:
        return from_reply(reply)
    slot = next((item for item in (reply.body or {}).get("slots") or [] if item.get("index") == index), None)
    if slot is None:
        return fail(f"{mid} 没有 {index} 号槽。", "NOT_FOUND", status=404)
    phase = slot.get("phase")
    effects: list[str] = [f"{mid} 的 {index} 号槽现在{phase_text(phase)}"]
    if action in {"slot_load", "slot_test"} and phase not in {"IDLE", "COMPLETED"}:
        return fail(f"{mid} 的 {index} 号槽现在{phase_text(phase)}，不能装板。", "CONFLICT", status=409)
    if action == "slot_abort" and phase in {"IDLE", "COMPLETED"}:
        return fail(f"{mid} 的 {index} 号槽没有在测试，不需要中止。", "CONFLICT", status=409)
    sentence = {
        "slot_load": f"把板 {args.get('serial_number')} 装到 {mid} 的 {index} 号槽",
        "slot_start": f"让 {mid} 的 {index} 号槽开始测试",
        "slot_test": f"把板 {args.get('serial_number')} 装到 {mid} 的 {index} 号槽并开始测试",
        "slot_abort": f"中止 {mid} 的 {index} 号槽，松开并取下板",
        "slot_clear_error": f"清除 {mid} 的 {index} 号槽的错误",
    }[action]
    if action == "slot_abort" and slot.get("run_id"):
        effects.append(f"记录 {slot['run_id']} 将被标记为中止")
    return Preview(sentence, effects)


def _production_body(args: dict) -> dict | None:
    body = {
        "machine_ids": _targets(args),
        "plan_id": args.get("plan_id"),
        "plan_version": args.get("plan_version"),
        "batch_id": args.get("batch_id"),
        "serial_numbers": args.get("serial_numbers"),
        "auto_recover": bool(args.get("auto_recover")),
        "max_count": args.get("max_count"),
    }
    return {key: value for key, value in body.items() if value is not None}


def _production_missing(args: dict) -> dict | None:
    if not _targets(args) or not args.get("plan_id") or args.get("plan_version") is None:
        return missing("machine_ids", "plan_id", "plan_version")
    if args.get("batch_id") and args.get("serial_numbers"):
        return bad("batch_id 和 serial_numbers 只能给一个。")
    if not args.get("batch_id") and not args.get("serial_numbers"):
        return missing("batch_id 或 serial_numbers")
    return None


async def _precheck(c: Ctx, args: dict) -> dict:
    reply = await c.post("/production/precheck", _production_body(args))
    if not reply.ok:
        return from_reply(reply)
    body = reply.body or {}
    issues = body.get("issues") or []
    danger = [item for item in issues if item.get("level") == "danger"]
    warns = [item for item in issues if item.get("level") == "warn"]
    if danger:
        text = "下发前检查没通过：" + "；".join(item.get("message", "") for item in danger) + "。"
        return fail(text, "VALIDATION_ERROR", status=422, detail=body)
    text = "下发前检查通过。" + ("提醒：" + "；".join(item.get("message", "") for item in warns) + "。" if warns else "")
    return ok(text, body)


async def _start_preview(c: Ctx, args: dict):
    if (problem := _production_missing(args)) is not None:
        return problem
    checked = await _precheck(c, args)
    if not checked.get("ok"):
        return checked
    source = f"批次 {args['batch_id']}" if args.get("batch_id") else f"{len(args['serial_numbers'])} 片指定的板"
    recover = "故障后自动恢复并继续" if args.get("auto_recover") else "故障时停住，不自动恢复"
    warns = [item.get("message", "") for item in (checked.get("data") or {}).get("issues") or [] if item.get("level") == "warn"]
    sentence = f"让 {join_ids(_targets(args))} 用方案 {args['plan_id']} v{args['plan_version']} 连续测试{source}，{recover}"
    return Preview(sentence, warns, precheck=checked.get("data"))


async def _stop_preview(c: Ctx, args: dict):
    batch = args.get("batch_id")
    if not batch:
        reply = await c.get("/production")
        if not reply.ok:
            return from_reply(reply)
        current = reply.body or {}
        batch = current.get("batch_id")
        if not batch:
            return fail("现在没有在跑连续生产。", "CONFLICT", status=409)
    return Preview(f"停止批次 {batch} 的连续生产", ["不再取新板，正在测的那一片会测完"], args={"batch_id": batch})


async def _need_catalog(c: Ctx, summary: str) -> dict:
    scenarios = await c.get("/sim/scenarios")
    faults = await c.get("/sim/fault-catalog")
    hints = []
    if scenarios.ok:
        hints.append("可用场景：" + join_ids([item.get("name") for item in (scenarios.body or {}).get("items") or []]))
    if faults.ok:
        hints.append("可用故障：" + join_ids([item.get("kind") for item in (faults.body or {}).get("items") or []]))
    return fail(summary, "BAD_ARGUMENT", hints=hints or None)


# ---------- 执行 ----------


async def _run(c: Ctx, action: str, values: dict, idem: str | None) -> dict:
    if action in MACHINE_ACTIONS:
        return await _each_machine(c, action, values, idem)
    if action == "slot_load":
        return await _slot_call(c, values, "load", {"serial_number": values.get("serial_number")}, idem, "装上了板 {serial}，还没开始测试")
    if action == "slot_start":
        return await _slot_call(c, values, "start", None, idem, "开始测试")
    if action == "slot_test":
        loaded = await _slot_call(c, values, "load", {"serial_number": values.get("serial_number")}, _sub(idem, "load"), "装上了板 {serial}")
        if not loaded.get("ok"):
            return loaded
        return await _slot_call(c, values, "start", None, _sub(idem, "start"), "装上板 {serial} 并开始测试")
    if action == "slot_abort":
        return await _slot_call(c, values, "abort", None, idem, "已中止，板已松开")
    if action == "slot_clear_error":
        if not values.get("machine_id") or values.get("slot_index") is None:
            return missing("machine_id", "slot_index")
        return await _slot_call(c, values, "clear-error", None, idem, "错误已清除")
    if action == "create_batch":
        return await _create_batch(c, values)
    if action == "production_precheck":
        if (problem := _production_missing(values)) is not None:
            return problem
        return await _precheck(c, values)
    if action == "production_start":
        reply = await c.post("/production/start", _production_body(values), idem=idem)
        if not reply.ok:
            return from_reply(reply)
        out = reply.body or {}
        skipped = out.get("skipped") or []
        text = f"连续生产已开始：批次 {out.get('batch_id')}，参与 {join_ids(out.get('accepted'))}。"
        if skipped:
            text += "跳过：" + "；".join(f"{item.get('machine_id')}（{item.get('reason')}）" for item in skipped) + "。"
        return ok(text, out)
    if action == "production_stop":
        reply = await c.post("/production/stop", {"batch_id": values.get("batch_id")}, idem=idem)
        if not reply.ok:
            return from_reply(reply)
        return ok(f"批次 {values.get('batch_id')} 的连续生产已停止，正在测的那一片会测完。", reply.body)
    if action == "sim_speed":
        if not values.get("machine_ids"):
            return missing("machine_ids")
        if not values.get("speed") or values["speed"] <= 0:
            return bad("speed 必须大于 0。")
        body = {"speed": values.get("speed"), "machine_ids": values["machine_ids"]}
        reply = await c.put("/sim/clock", body, idem=idem)
        if not reply.ok:
            return from_reply(reply)
        return ok(f"{join_ids(values['machine_ids'])} 的仿真倍率已改为 {values.get('speed')}。", reply.body)
    if action == "requeue":
        serial = values.get("serial_number")
        if not serial:
            return missing("serial_number")
        reply = await c.post(f"/products/{serial}/requeue", None, idem=idem)
        if not reply.ok:
            return from_reply(reply)
        return ok(f"标准样品 {serial} 已放回待测。", reply.body)
    if action == "sim_scenario":
        reply = await c.post(f"/sim/scenarios/{values.get('name')}/apply", {"machine_id": values.get("machine_id")}, idem=idem)
        if not reply.ok:
            return from_reply(reply)
        return ok(f"{values.get('machine_id')} 已应用场景「{values.get('name')}」。", reply.body)
    if action == "sim_fault":
        body = {"machine_id": values.get("machine_id"), "kind": values.get("kind"), "slot_index": values.get("slot_index")}
        reply = await c.post("/sim/faults", body, idem=idem)
        if not reply.ok:
            return from_reply(reply)
        return ok(f"已给 {values.get('machine_id')} 注入故障 {values.get('kind')}。", reply.body)
    return missing("action")


def _sub(idem: str | None, suffix: str) -> str | None:
    return f"{idem}:{suffix}" if idem else None


async def _each_machine(c: Ctx, action: str, values: dict, idem: str | None) -> dict:
    ids = _targets(values)
    if not ids:
        return missing("machine_ids")
    path = MACHINE_ACTIONS[action]
    body = {"on": values.get("on")} if action == "maintenance" else None
    done, failed = [], []
    for mid in ids:
        reply = await c.post(f"/machines/{mid}/{path}", body, idem=_sub(idem, mid))
        if reply.ok:
            done.append({"machine_id": mid, "status": (reply.body or {}).get("status")})
        else:
            failed.append({"machine_id": mid, "code": reply.code, "reason": reply.message or reply.code})
    verb = {"power_on": "已上电", "power_off": "已关机", "reset": "已复位", "maintenance": "已切换维修模式"}[action]
    if not done:
        first = failed[0]
        return fail(f"{join_ids([f['machine_id'] for f in failed])} 都没有成功：{first['reason']}。", first["code"], detail={"done": [], "failed": failed})
    if failed:
        text = (
            f"{join_ids([d['machine_id'] for d in done])} {verb}。"
            "没成功：" + "；".join(f"{f['machine_id']}（{f['reason']}）" for f in failed) + "。"
        )
        return fail(
            text,
            "PARTIAL",
            detail={"done": done, "failed": failed},
            hints=["已经成功的机台不要再发。再次批准会跳过已成功的，并重试没成功的。"],
        )
    return ok(f"{join_ids([d['machine_id'] for d in done])} {verb}。", {"done": done, "failed": []})


async def _slot_call(c: Ctx, values: dict, op: str, body: dict | None, idem: str | None, done_text: str) -> dict:
    mid, index = values.get("machine_id"), values.get("slot_index")
    reply = await c.post(f"/machines/{mid}/slots/{index}/{op}", body, idem=idem)
    if not reply.ok:
        return from_reply(reply)
    out = reply.body or {}
    text = f"{mid} 的 {index} 号槽" + done_text.format(serial=values.get("serial_number") or "")
    if out.get("run_id"):
        text += f"，记录 {out['run_id']}"
    return ok(text + "。", out)


async def _requeue_preview(c: Ctx, args: dict):
    serial = args.get("serial_number")
    if not serial:
        return missing("serial_number")
    reply = await c.get(f"/products/{serial}")
    if not reply.ok:
        return from_reply(reply)
    board = reply.body or {}
    if board.get("golden") is False or (board.get("state") and board.get("state") != "TESTED"):
        return fail(f"{serial} 不是已测完的标准样品，不能放回待测。", "CONFLICT", status=409)
    return Preview(f"把标准样品 {serial} 放回待测", ["状态回到待测后，连续生产可以再次取到它"])


async def _batch_preview(c: Ctx, args: dict):
    model = (args.get("model") or "").strip()
    if not model:
        return missing("model")
    drawn = _draw_batch(args)
    if isinstance(drawn, dict):
        return drawn
    count, yield_rate, defect_ratio = drawn
    reply = await c.get("/models")
    if not reply.ok:
        return from_reply(reply)
    names = {item.get("model") for item in reply.body or [] if isinstance(item, dict)}
    if names and model not in names:
        return fail(f"没有型号 {model}。", "VALIDATION_ERROR", status=422, hints=["用 vc_data models 查看已有型号"])
    stored = {
        "model": model,
        "count": count,
        "defect_ratio": defect_ratio,
        "batch_factor": args.get("batch_factor") if args.get("batch_factor") is not None else 1.0,
        "yield_rate": yield_rate,
    }
    return Preview(
        f"生成 {count} 片型号 {model} 的待测板，良率 {yield_rate}，次品比例 {defect_ratio}",
        ["序列号由平台分配", "这里没有每一片的等级、缺陷和真实热阻"],
        args=stored,
    )


def _draw_batch(args: dict) -> tuple[int, float, float] | dict:
    if args.get("count_random"):
        low, high = args.get("count_min"), args.get("count_max")
        if low is None or high is None or int(low) < 1 or int(high) < int(low):
            return bad("随机片数要给 count_min 和 count_max，下限至少为 1，且下限不能大于上限。")
        count = random.randint(int(low), int(high))
    elif args.get("count") is not None:
        count = int(args["count"])
        if count < 1:
            return bad("数量至少为 1 片。")
    else:
        return missing("count")
    if args.get("yield_random"):
        low, high = args.get("yield_min"), args.get("yield_max")
        if low is None or high is None or not 0 <= float(low) <= float(high) <= 1:
            return bad("随机良率要给 yield_min 和 yield_max，都要在 0 到 1 之间，且下限不能大于上限。")
        yield_rate = float(low) if float(low) == float(high) else round(random.uniform(float(low), float(high)), 4)
    elif args.get("yield_rate") is not None:
        yield_rate = float(args["yield_rate"])
        if not 0 <= yield_rate <= 1:
            return bad("良率必须在 0 到 1 之间。1 表示没有次品。")
    elif args.get("defect_ratio") is not None:
        defect = float(args["defect_ratio"])
        if not 0 <= defect <= 1:
            return bad("次品比例必须在 0 到 1 之间。")
        return count, round(1 - defect, 6), defect
    else:
        return missing("yield_rate 或 defect_ratio")
    return count, yield_rate, round(min(1.0, max(0.0, 1 - yield_rate)), 6)


async def _create_batch(c: Ctx, values: dict) -> dict:
    if not values.get("model") or not values.get("count"):
        return missing("model", "count")
    body = {key: values[key] for key in ("model", "count", "defect_ratio", "batch_factor") if values.get(key) is not None}
    reply = await c.post("/batches", body, timeout=60)
    if not reply.ok:
        return from_reply(reply)
    out = reply.body or {}
    batch = out.get("batch") or {}
    serials = out.get("serial_numbers") or []
    text = f"已生成 {len(serials) or values['count']} 片 {values['model']}，批次 {batch.get('batch_id')}。连续生产时用这个批次号。"
    return ok(text, {"batch": batch, "serial_numbers": serials[:20], "total": len(serials)})
