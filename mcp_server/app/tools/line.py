import asyncio
from typing import Literal

from app.result import fail, from_reply, missing, ok
from app.state import Ctx, ctx
from app.text import BUSY_PHASES, COMM_STATUS, clamp_limit, join_ids, phase_text, status_text

LineAction = Literal["overview", "machines", "machine", "slot", "production", "alarms", "attribution", "search"]
Window = Literal["1h", "2h", "8h", "24h", "7d"]


async def vc_line(
    action: LineAction,
    machine_id: str | None = None,
    slot_index: int | None = None,
    status: str | None = None,
    comm: str | None = None,
    acked: bool | None = None,
    level: str | None = None,
    alarm_id: str | None = None,
    q: str | None = None,
    window: Window = "8h",
    detail: bool = False,
    cursor: str | None = None,
    limit: int = 20,
    loaded: bool = False,
) -> dict:
    """VC-TestOS 产线实时现状（只读）。回答「现在线上怎么样」「这台机在干什么」「这个槽测到哪了」。

    action:
    - overview：一次拿到全线概况：在线机台、槽位占用、本班测试数与良率、未确认告警、连续生产、同步状态。window 取 1h/2h 时统计近 2 小时，其余为本班 8 小时。
    - machines：机台列表。可用 status（READY/FAULT/MAINTENANCE/OFFLINE…）、comm（ONLINE/DEGRADED/DISCONNECTED）筛选。
    - machine：一台机的详情和全部槽位，要 machine_id。detail=true 返回能力范围等完整字段。loaded=true 时再读集群上现在装的方案；没装也算成功，档案里的 plan_id 不能代替这次读取。
    槽位步骤依次是空闲、复位、预热、放板、夹紧、测量、恢复。错误表示这一步失败。读数里 99999 和 9999 表示接触不良，-1 表示采集无应答，-2 表示回答无法解析。
    - slot：一个槽的阶段、进度、温度、真空和当前记录，要 machine_id、slot_index（从 1 开始）。detail=true 附带过程曲线。
    - production：当前连续生产的批次、方案版本和剩余数量。
    - alarms：告警列表，可按 acked、machine_id、level（critical/major/minor）筛选，分页用 cursor、limit。
    - attribution：某条告警的归因结论，要 alarm_id。
    - search：按关键字找机台、批次、方案和测试记录，要 q。
    """
    c = ctx()
    if action == "overview":
        return await _overview(c, window)
    if action == "machines":
        return await _machines(c, status, comm, detail)
    if action == "machine":
        if not machine_id:
            return missing("machine_id")
        return await _machine(c, machine_id, detail, loaded)
    if action == "slot":
        if not machine_id or slot_index is None:
            return missing("machine_id", "slot_index")
        return await _slot(c, machine_id, slot_index, detail)
    if action == "production":
        return await _production(c)
    if action == "alarms":
        return await _alarms(c, acked, machine_id, level, cursor, limit)
    if action == "attribution":
        if not alarm_id:
            return missing("alarm_id")
        return await _attribution(c, alarm_id)
    if action == "search":
        if not q:
            return missing("q")
        return await _search(c, q, limit)
    return missing("action")


async def _overview(c: Ctx, window: str) -> dict:
    span = "2h" if window in {"1h", "2h"} else "shift"
    kpi, pipeline, production, jobs = await asyncio.gather(
        c.get("/stats/kpi", {"range": span}),
        c.get("/stats/pipeline"),
        c.get("/production"),
        c.get("/sync/jobs/status"),
    )
    if not kpi.ok:
        return from_reply(kpi)
    k = kpi.body or {}
    prod = production.body if production.ok else None
    failed_jobs = [item.get("key") for item in ((jobs.body or {}).get("items") or []) if jobs.ok and item.get("failed")]
    label = "近 2 小时" if span == "2h" else "本班"
    parts = [
        f"在线 {k.get('online', 0)}/{k.get('total', 0)} 台",
        f"忙碌槽 {k.get('busy_slots', 0)}/{k.get('slot_total', 0)}，出错槽 {k.get('error_slots', 0)}",
        f"{label}测试 {k.get('tests', 0)} 片，良率 {float(k.get('yield_rate') or 0):.1f}%",
        f"未确认告警 {k.get('open_alarms', 0)} 条（严重 {k.get('critical_alarms', 0)}）",
        f"连续生产：批次 {prod['batch_id']} 剩余 {prod.get('queue_remaining', 0)} 片" if prod else "没有在跑连续生产",
    ]
    if failed_jobs:
        parts.append(f"同步任务异常：{join_ids(failed_jobs)}")
    data = {
        "kpi": k,
        "pipeline": pipeline.body if pipeline.ok else None,
        "production": prod,
        "sync_jobs": (jobs.body or {}).get("items") if jobs.ok else None,
    }
    return ok("；".join(parts) + "。", data)


def _brief(machine: dict) -> dict:
    slots = machine.get("slots") or []
    return {
        "machine_id": machine.get("machine_id"),
        "status": machine.get("status"),
        "comm_status": machine.get("comm_status"),
        "plan_id": machine.get("plan_id"),
        "plan_version": machine.get("plan_version"),
        "speed": machine.get("speed"),
        "busy_slots": sum(1 for slot in slots if slot.get("phase") in BUSY_PHASES),
        "error_slots": [slot.get("index") for slot in slots if slot.get("phase") == "ERROR"],
        "slot_count": machine.get("slot_count") or len(slots),
        "alarm": machine.get("alarm") or "",
        "yield_recent": machine.get("yield_recent"),
    }


def _slot_brief(slot: dict) -> dict:
    keys = ("index", "phase", "serial_number", "progress", "run_id", "last_error", "t0", "t1", "power_w", "vacuum_kpa")
    return {key: slot.get(key) for key in keys}


async def _machines(c: Ctx, status: str | None, comm: str | None, detail: bool) -> dict:
    reply = await c.get("/machines")
    if not reply.ok:
        return from_reply(reply)
    rows = [row for row in reply.body or [] if isinstance(row, dict)]
    if status:
        rows = [row for row in rows if str(row.get("status")).upper() == status.upper()]
    if comm:
        rows = [row for row in rows if str(row.get("comm_status")).upper() == comm.upper()]
    if not rows:
        return ok("没有符合条件的机台。", {"machines": []})
    brief = "；".join(
        f"{row.get('machine_id')} {status_text(row.get('status'))}"
        + ("、" + COMM_STATUS.get(row.get("comm_status"), "") if row.get("comm_status") != "ONLINE" else "")
        for row in rows
    )
    machines = rows if detail else [_brief(row) for row in rows]
    return ok(f"共 {len(rows)} 台：{brief}。", {"machines": machines})


async def _machine(c: Ctx, machine_id: str, detail: bool, loaded: bool = False) -> dict:
    reply = await c.get(f"/machines/{machine_id}")
    if not reply.ok:
        return from_reply(reply)
    m = reply.body or {}
    slots = m.get("slots") or []
    busy = [slot for slot in slots if slot.get("phase") in BUSY_PHASES]
    errors = [slot for slot in slots if slot.get("phase") == "ERROR"]
    text = (
        f"{machine_id} {status_text(m.get('status'))}，{COMM_STATUS.get(m.get('comm_status'), m.get('comm_status') or '')}；"
        f"方案 {m.get('plan_id') or '未装载'}{' v' + str(m.get('plan_version')) if m.get('plan_version') else ''}；"
        f"{len(slots)} 个槽，{len(busy)} 个在忙，{len(errors)} 个出错"
    )
    if errors:
        text += "（" + "，".join(f"{slot.get('index')} 号：{slot.get('last_error') or '出错'}" for slot in errors) + "）"
    data = m if detail else {**_brief(m), "slots": [_slot_brief(slot) for slot in slots]}
    if loaded:
        live = await c.get(f"/machines/{machine_id}/loaded-plan")
        if not live.ok:
            return from_reply(live)
        data = {**data, "loaded_plan": live.body}
        plan = (live.body or {}).get("plan")
        if plan:
            text += f"；集群上现在是 {plan.get('name') or plan.get('plan_id')} {plan.get('plan_id')} v{plan.get('version')}"
        else:
            text += "；集群上现在没有装方案"
    return ok(text + "。", data)


async def _slot(c: Ctx, machine_id: str, slot_index: int, detail: bool) -> dict:
    reply = await c.get(f"/machines/{machine_id}")
    if not reply.ok:
        return from_reply(reply)
    slot = next((item for item in (reply.body or {}).get("slots") or [] if item.get("index") == slot_index), None)
    if slot is None:
        return fail(f"{machine_id} 没有 {slot_index} 号槽。", "NOT_FOUND", status=404)
    text = f"{machine_id} 的 {slot_index} 号槽{phase_text(slot.get('phase'))}"
    if slot.get("serial_number"):
        text += f"，板 {slot['serial_number']}"
    if slot.get("phase") == "SAMPLING":
        text += f"，进度 {float(slot.get('progress') or 0):.0f}%，T0 {slot.get('t0')}℃ / T1 {slot.get('t1')}℃"
    if slot.get("last_error"):
        text += f"，错误：{slot['last_error']}"
    data: dict = {"slot": slot}
    if detail:
        curve = await c.get(f"/machines/{machine_id}/slots/{slot_index}/curve")
        data["curve"] = curve.body if curve.ok else None
    return ok(text + "。", data)


async def _production(c: Ctx) -> dict:
    reply = await c.get("/production")
    if not reply.ok:
        return from_reply(reply)
    prod = reply.body
    if not prod:
        return ok("现在没有在跑连续生产。", {"production": None})
    return ok(
        f"连续生产中：批次 {prod.get('batch_id')}，方案 {prod.get('plan_id')} v{prod.get('plan_version')}，剩余 {prod.get('queue_remaining', 0)} 片。",
        {"production": prod},
    )


async def _alarms(c: Ctx, acked, machine_id, level, cursor, limit) -> dict:
    reply = await c.get("/alarms", {"acked": acked, "machine_id": machine_id, "level": level, "cursor": cursor, "limit": clamp_limit(limit)})
    if not reply.ok:
        return from_reply(reply)
    body = reply.body or {}
    items = body.get("items") or []
    open_count = sum(1 for item in items if not item.get("acked"))
    top = "；".join(f"{item.get('machine_id')}{'#' + str(item['slot_index']) if item.get('slot_index') else ''} {item.get('code')}：{item.get('message')}" for item in items[:3])
    text = f"返回 {len(items)} 条告警，其中未确认 {open_count} 条。" + (f"最近：{top}。" if top else "")
    return ok(text, {"alarms": items}, next_cursor=body.get("next_cursor"))


async def _attribution(c: Ctx, alarm_id: str) -> dict:
    reply = await c.get(f"/alarms/{alarm_id}/attribution")
    if not reply.ok:
        return from_reply(reply)
    a = reply.body or {}
    if a.get("status") != "done":
        return ok(f"告警 {alarm_id} 的归因状态：{a.get('status')}，还没有结论。", a)
    conf = a.get("confidence")
    text = f"归因：{a.get('category') or '未分类'}" + (f"（置信度 {conf:.0%}）" if isinstance(conf, (int, float)) else "") + f"。{a.get('summary') or ''}"
    return ok(text, a)


async def _search(c: Ctx, q: str, limit: int) -> dict:
    reply = await c.get("/search", {"q": q, "limit": clamp_limit(limit, 10)})
    if not reply.ok:
        return from_reply(reply)
    body = reply.body or {}
    counts = {key: len(body.get(key) or []) for key in ("machines", "batches", "plans", "runs")}
    total = sum(counts.values())
    text = f"「{q}」找到 {total} 条：机台 {counts['machines']}、批次 {counts['batches']}、方案 {counts['plans']}、记录 {counts['runs']}。"
    return ok(text, body)
