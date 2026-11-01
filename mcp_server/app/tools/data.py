import asyncio
from typing import Literal

from app.result import bad, from_reply, missing, ok
from app.state import Ctx, ctx
from app.text import WINDOW_HOURS, clamp_limit, join_ids, pct, window_range

DataAction = Literal[
    "runs",
    "run",
    "ground_truth",
    "batches",
    "batch",
    "compare",
    "trend",
    "models",
    "plans",
    "plan",
    "plan_history",
    "calibration",
    "calibration_history",
    "audit",
    "sim_catalog",
    "boards",
    "board",
    "defect_kinds",
    "export",
]
Window = Literal["1h", "2h", "8h", "24h", "7d"]
Metric = Literal["output", "anomaly", "rc_bias"]


async def vc_data(
    action: DataAction,
    run_id: str | None = None,
    batch_id: str | None = None,
    batch_ids: list[str] | None = None,
    machine_id: str | None = None,
    model: str | None = None,
    plan_id: str | None = None,
    version: int | None = None,
    passed: bool | None = None,
    status: str | None = None,
    state: Literal["running", "done", "stopped"] | None = None,
    draft: bool | None = None,
    q: str | None = None,
    metric: Metric = "output",
    window: Window = "8h",
    from_ms: int | None = None,
    to_ms: int | None = None,
    detail: bool = False,
    cursor: str | None = None,
    limit: int = 20,
    since: float | None = None,
    serial_number: str | None = None,
    board_state: Literal["NEW", "IN_MACHINE", "TESTED"] | None = None,
    golden: bool | None = None,
    limits_plan_id: str | None = None,
) -> dict:
    """VC-TestOS 历史数据与目录（只读）。用于跨批次分析、失败原因定位、查方案和补偿。良率只按测试记录算，不用批次的缺陷比例。

    action:
    - runs：测试记录列表。可按 machine_id、batch_id、passed、status（RUNNING/DONE/ABORTED）、q、时间（window 或 from_ms/to_ms）筛选。
    - run：一条记录的判定项和失败项，要 run_id。detail=true 附带采样。since 是已见过的最大 t_s，limit 是这次最多条数。续读时不要把 since 改小。
    - ground_truth：仿真真值（仅仿真数据源），要 run_id。
    - batches：批次统计（数量、合格、不合格、中止、Rc、主要失败项），可按 model、state、q 筛选。
    - batch：一个批次的统计，要 batch_id。
    - compare：对比 2–5 个批次的良率、失败项分布、各机台良率。给 batch_ids；不给时用 model 取该型号最近 3 个批次。
    - trend：metric=output 产出与良率（按 5 分钟）、anomaly 异常分类趋势、rc_bias 各机台 Rc 偏差。
    - models：型号目录和参考功率。
    - plans：方案列表，可用 q（名称或编号）和 draft（true 只看草稿，false 只看已发布）过滤。
    - plan：方案详情，要 plan_id，可给 version。
    - plan_history：某台机用过的方案版本和测试数，要 machine_id。
    - calibration：某台机的通道偏差、漂移、当前补偿和补偿建议，要 machine_id。
    - calibration_history：补偿修改历史，要 machine_id。
    - audit：操作审计记录，可按 machine_id 筛选。
    - sim_catalog：仿真场景和可注入的故障种类（仅仿真数据源）。用户明确要求切场景或注入故障时才查，再交给 vc_operate。
    - boards：按 model、batch_id、board_state（NEW 待测、IN_MACHINE 在机、TESTED 已测完）、golden 查板。没有等级、单板缺陷和真实热阻。
    - board：按 serial_number 看一片板，字段同上。
    - defect_kinds：缺陷种类和现象。这是目录，不能据此判断某一片板有没有缺陷。
    - export：导出已完成且保留结果的生产 CSV，必填 limits_plan_id，可选 version。表头三行是列名、上限、下限。只读。
    读数里 99999 和 9999 表示接触不良，-1 表示采集无应答，-2 表示回答无法解析。60 秒附近的快照不参与合格判定。记录可以按时间筛，但导出的生产表用批次和序列号区分，不把墙钟时间当成测试完成时刻。
    """
    c = ctx()
    if action == "runs":
        return await _runs(c, machine_id, batch_id, passed, status, q, window, from_ms, to_ms, cursor, limit)
    if action == "run":
        if not run_id:
            return missing("run_id")
        return await _run(c, run_id, detail, since, limit)
    if action == "ground_truth":
        if not run_id:
            return missing("run_id")
        return await _simple(c, f"/runs/{run_id}/ground-truth", f"记录 {run_id} 的仿真真值。")
    if action == "batches":
        return await _batches(c, model, state, q, cursor, limit)
    if action == "batch":
        if not batch_id:
            return missing("batch_id")
        return await _batch(c, batch_id)
    if action == "compare":
        return await _compare(c, batch_ids, model)
    if action == "trend":
        return await _trend(c, metric, window, from_ms, to_ms)
    if action == "models":
        return await _models(c)
    if action == "plans":
        return await _plans(c, q, draft, detail)
    if action == "plan":
        if not plan_id:
            return missing("plan_id")
        return await _plan(c, plan_id, version)
    if action == "plan_history":
        if not machine_id:
            return missing("machine_id")
        return await _plan_history(c, machine_id)
    if action == "calibration":
        if not machine_id:
            return missing("machine_id")
        return await _calibration(c, machine_id)
    if action == "calibration_history":
        if not machine_id:
            return missing("machine_id")
        reply = await c.get(f"/machines/{machine_id}/compensation/history", {"cursor": cursor, "limit": clamp_limit(limit)})
        if not reply.ok:
            return from_reply(reply)
        items = (reply.body or {}).get("items") or []
        return ok(f"{machine_id} 有 {len(items)} 条补偿修改记录。", {"items": items}, next_cursor=(reply.body or {}).get("next_cursor"))
    if action == "audit":
        reply = await c.get("/audit", {"machine_id": machine_id, "cursor": cursor, "limit": clamp_limit(limit)})
        if not reply.ok:
            return from_reply(reply)
        items = (reply.body or {}).get("items") or []
        return ok(f"返回 {len(items)} 条操作记录。", {"items": items}, next_cursor=(reply.body or {}).get("next_cursor"))
    if action == "boards":
        return await _boards(c, model, batch_id, board_state, golden, cursor, limit)
    if action == "board":
        if not serial_number:
            return missing("serial_number")
        return await _board(c, serial_number)
    if action == "defect_kinds":
        return await _defect_kinds(c)
    if action == "export":
        if not limits_plan_id:
            return missing("limits_plan_id")
        return await _export(c, limits_plan_id, version, batch_id)
    if action == "sim_catalog":
        scenarios, faults = await asyncio.gather(c.get("/sim/scenarios"), c.get("/sim/fault-catalog"))
        if not scenarios.ok:
            return from_reply(scenarios)
        s_items = (scenarios.body or {}).get("items") or []
        f_items = (faults.body or {}).get("items") or [] if faults.ok else []
        text = f"仿真场景 {len(s_items)} 个：{join_ids([item.get('name') for item in s_items])}；故障种类 {len(f_items)} 个。"
        return ok(text, {"scenarios": s_items, "faults": f_items})
    return missing("action")


def _yield(passed: int, failed: int) -> str:
    return pct(passed, passed + failed)


async def _runs(c: Ctx, machine_id, batch_id, passed, status, q, window, from_ms, to_ms, cursor, limit) -> dict:
    params = {
        "machine_id": machine_id,
        "batch_id": batch_id,
        "passed": None if passed is None else ("true" if passed else "false"),
        "status": status,
        "q": q,
        "cursor": cursor,
        "limit": clamp_limit(limit),
    }
    if from_ms or to_ms or not (machine_id or batch_id or q):
        start, end = window_range(window, from_ms, to_ms)
        params["from"], params["to"] = start, end
    reply = await c.get("/runs", params)
    if not reply.ok:
        return from_reply(reply)
    body = reply.body or {}
    items = body.get("items") or []
    good = sum(1 for item in items if item.get("passed") is True)
    badn = sum(1 for item in items if item.get("passed") is False and item.get("status") != "ABORTED")
    aborted = sum(1 for item in items if item.get("status") == "ABORTED")
    fails: dict[str, int] = {}
    for item in items:
        for name in item.get("fail_items") or []:
            fails[name] = fails.get(name, 0) + 1
    top = "、".join(f"{name} {count} 次" for name, count in sorted(fails.items(), key=lambda kv: -kv[1])[:3])
    text = f"这一页 {len(items)} 条记录：合格 {good}，不合格 {badn}，中止 {aborted}。" + (f"主要失败项：{top}。" if top else "")
    return ok(text, {"runs": items}, next_cursor=body.get("next_cursor"))


async def _run(c: Ctx, run_id: str, detail: bool, since: float | None = None, limit: int = 20) -> dict:
    reply = await c.get(f"/runs/{run_id}")
    if not reply.ok:
        return from_reply(reply)
    run = reply.body or {}
    verdict = {True: "合格", False: "不合格"}.get(run.get("passed"), run.get("status") or "未判定")
    text = f"{run_id}（{run.get('machine_id')} {run.get('slot_index')} 号槽，板 {run.get('serial_number')}）{verdict}"
    if run.get("fail_items"):
        text += f"，失败项：{'、'.join(run['fail_items'])}"
    if run.get("rc") is not None:
        text += f"，Rc {run['rc']}"
    data: dict = {"run": run}
    if detail:
        window = max(1, min(int(limit or 50), 2000))
        samples = await c.get(f"/runs/{run_id}/samples", {"since": since, "limit": window})
        data["samples"] = samples.body if samples.ok else None
        if since is not None and samples.ok and not ((samples.body or {}).get("points")):
            text += f"。没有比 t_s {since} 更新的采样"
    return ok(text + "。", data)


def _stat_line(row: dict) -> str:
    return (
        f"{row.get('batch_id')}（{row.get('model')}，{row.get('state')}）测 {row.get('tested', 0)}/{row.get('count', 0)} 片，"
        f"良率 {_yield(row.get('passed', 0), row.get('failed', 0))}"
        + (f"，主要失败 {row['top_fail']}" if row.get("top_fail") else "")
    )


async def _batches(c: Ctx, model, state, q, cursor, limit) -> dict:
    reply = await c.get("/batch-stats", {"model": model, "state": state, "q": q, "cursor": cursor, "limit": clamp_limit(limit)})
    if not reply.ok:
        return from_reply(reply)
    body = reply.body or {}
    items = body.get("items") or []
    if not items:
        return ok("没有符合条件的批次统计。", {"batches": []})
    text = f"{len(items)} 个批次：" + "；".join(_stat_line(row) for row in items[:5]) + ("……" if len(items) > 5 else "") + "。"
    return ok(text, {"batches": items}, next_cursor=body.get("next_cursor"))


async def _batch(c: Ctx, batch_id: str) -> dict:
    reply = await c.get(f"/batch-stats/{batch_id}")
    if not reply.ok:
        return from_reply(reply)
    return ok(_stat_line(reply.body or {}) + "。", reply.body)


async def _compare(c: Ctx, batch_ids: list[str] | None, model: str | None) -> dict:
    ids = [item for item in batch_ids or [] if item]
    if not ids:
        if not model:
            return bad("compare 需要 batch_ids，或者给 model 取最近 3 个批次。", "补上 batch_ids 或 model。")
        recent = await c.get("/batch-stats", {"model": model, "limit": 3})
        if not recent.ok:
            return from_reply(recent)
        ids = [row.get("batch_id") for row in (recent.body or {}).get("items") or [] if row.get("batch_id")]
        if not ids:
            return ok(f"型号 {model} 还没有批次统计。", {"batches": []})
    if len(ids) > 5:
        return bad("compare 最多对比 5 个批次。")
    reply = await c.get("/reports/data", {"batch_ids": ",".join(ids)}, timeout=60)
    if not reply.ok:
        return from_reply(reply)
    body = reply.body or {}
    rows = [
        {
            "batch_id": row.get("batch_id"),
            "model": row.get("model"),
            "tested": row.get("tested"),
            "passed": row.get("passed"),
            "failed": row.get("failed"),
            "aborted": row.get("aborted"),
            "yield": _yield(row.get("passed", 0), row.get("failed", 0)),
            "rc_mean": row.get("rc_mean"),
            "top_fail": row.get("top_fail"),
            "top_fail_count": row.get("top_fail_count"),
            "worst_machine_id": row.get("worst_machine_id"),
        }
        for row in body.get("batches") or []
    ]
    pareto = body.get("fail_pareto") or []
    lines = [f"{row['batch_id']} 良率 {row['yield']}（合格 {row['passed']}/不合格 {row['failed']}，Rc {row['rc_mean']}）" for row in rows]
    text = "；".join(lines) + "。"
    if pareto:
        text += "失败项：" + "、".join(f"{item.get('item')} {item.get('count')} 次" for item in pareto[:3]) + "。"
    data = {
        "batches": rows,
        "fail_pareto": pareto,
        "machine_yield": body.get("machine_yield"),
        "summary": body.get("summary"),
    }
    return ok(text, data)


async def _trend(c: Ctx, metric: str, window: str, from_ms, to_ms) -> dict:
    if metric == "rc_bias":
        reply = await c.get("/stats/rc-bias")
        if not reply.ok:
            return from_reply(reply)
        body = reply.body or {}
        items = sorted(body.get("items") or [], key=lambda item: -abs(item.get("bias") or 0))
        top = "、".join(f"{item.get('machine_id')} {item.get('bias'):+.3f}" for item in items[:3])
        return ok(f"全线 Rc 中位数 {body.get('median')}；偏差最大：{top or '无'}。", body)
    if metric == "anomaly":
        hours = WINDOW_HOURS.get(window, 8)
        reply = await c.get("/stats/anomaly-trend", {"hours": hours})
        if not reply.ok:
            return from_reply(reply)
        series = (reply.body or {}).get("series") or {}
        totals = {key: sum(values or []) for key, values in series.items()}
        text = f"近 {hours} 小时异常：" + "、".join(f"{key} {value}" for key, value in totals.items()) + "。"
        return ok(text, reply.body)
    start, end = window_range(window, from_ms, to_ms)
    reply = await c.get("/stats/agg5m", {"from": start, "to": end})
    if not reply.ok:
        return from_reply(reply)
    buckets = reply.body or []
    tests = sum(item.get("tests", 0) for item in buckets)
    good = sum(item.get("passed", 0) for item in buckets)
    failed = sum(item.get("failed", 0) for item in buckets)
    text = f"这段时间测试 {tests} 片，合格 {good}，不合格 {failed}，良率 {_yield(good, failed)}。"
    return ok(text, {"buckets": [item for item in buckets if item.get("tests")]})


async def _models(c: Ctx) -> dict:
    reply = await c.get("/models", timeout=30)
    if not reply.ok:
        return from_reply(reply)
    rows = reply.body or []
    text = f"{len(rows)} 个型号：" + "、".join(f"{row.get('model')}（{row.get('power_w')} W）" for row in rows) + "。"
    return ok(text, {"models": rows})


def _plan_brief(item: dict) -> dict:
    plan, meta = item.get("plan") or {}, item.get("meta") or {}
    return {
        "plan_id": plan.get("plan_id"),
        "version": plan.get("version"),
        "name": plan.get("name"),
        "power_w": plan.get("power_w"),
        "force_g": plan.get("force_g"),
        "duration_s": plan.get("duration_s"),
        "orientation": plan.get("orientation"),
        "draft": meta.get("draft"),
        "versions": meta.get("versions"),
        "updated_at": meta.get("updated_at"),
    }


async def _plans(c: Ctx, q: str | None, draft: bool | None, detail: bool) -> dict:
    reply = await c.get("/plans")
    if not reply.ok:
        return from_reply(reply)
    items = [item for item in reply.body or [] if isinstance(item, dict)]
    if draft is not None:
        items = [item for item in items if bool((item.get("meta") or {}).get("draft")) == draft]
    if q:
        key = q.lower()
        items = [item for item in items if key in str((item.get("plan") or {}).get("name", "")).lower() or key in str((item.get("plan") or {}).get("plan_id", "")).lower()]
    rows = items if detail else [_plan_brief(item) for item in items]
    names = "；".join(f"{_plan_brief(item)['plan_id']} v{_plan_brief(item)['version']} {_plan_brief(item)['name']}" for item in items[:5])
    text = f"{len(items)} 个方案" + (f"：{names}" if names else "") + ("……" if len(items) > 5 else "") + "。"
    return ok(text, {"plans": rows})


async def _plan(c: Ctx, plan_id: str, version: int | None) -> dict:
    reply = await c.get(f"/plans/{plan_id}", {"version": version})
    if not reply.ok:
        return from_reply(reply)
    plan = (reply.body or {}).get("plan") or {}
    text = (
        f"{plan_id} v{plan.get('version')}「{plan.get('name')}」：{plan.get('power_w')} W、{plan.get('force_g')} g、"
        f"{plan.get('duration_s')} 秒，起测 {plan.get('start_temp_c')}℃，判定项 {len(plan.get('limits') or [])} 个。"
    )
    return ok(text, reply.body)


async def _plan_history(c: Ctx, machine_id: str) -> dict:
    reply = await c.get(f"/machines/{machine_id}/plan-history")
    if not reply.ok:
        return from_reply(reply)
    items = (reply.body or {}).get("items") or []
    text = f"{machine_id} 用过 {len(items)} 个方案版本：" + "；".join(f"{item.get('plan_id')} v{item.get('version')}（{item.get('runs')} 次）" for item in items[:5]) + "。"
    return ok(text, {"items": items})


async def _calibration(c: Ctx, machine_id: str) -> dict:
    base = f"/machines/{machine_id}"
    bias, drifts, current, suggestion = await asyncio.gather(
        c.get(f"{base}/channel-bias"),
        c.get(f"{base}/drifts"),
        c.get(f"{base}/compensation"),
        c.get(f"{base}/compensation/suggestion"),
    )
    if not current.ok:
        return from_reply(current)
    now = {item.get("channel"): item.get("value") for item in (current.body or {}).get("items") or []}
    suggest = (suggestion.body or {}).get("items") or [] if suggestion.ok else []
    text = f"{machine_id} 当前补偿：" + ("、".join(f"{key} {value:+.3f}" for key, value in now.items()) or "无")
    if suggest:
        text += "；建议：" + "、".join(f"{item.get('channel')} {item.get('value'):+.3f}" for item in suggest)
    data = {
        "channel_bias": bias.body if bias.ok else None,
        "drifts": drifts.body if drifts.ok else None,
        "compensation": current.body,
        "suggestion": suggestion.body if suggestion.ok else None,
    }
    return ok(text + "。", data)


async def _simple(c: Ctx, path: str, summary: str) -> dict:
    reply = await c.get(path)
    if not reply.ok:
        return from_reply(reply)
    return ok(summary, reply.body)


def _board_text(board: dict) -> str:
    kind = "标准样品" if board.get("golden") else "普通样品"
    return (
        f"{board.get('serial_number')} 型号 {board.get('model')}，批次 {board.get('batch_id')}，"
        f"状态 {board.get('state')}，{kind}，已测 {board.get('test_count', 0)} 次"
    )


async def _boards(c: Ctx, model, batch_id, board_state, golden, cursor, limit) -> dict:
    reply = await c.get(
        "/products",
        {"model": model, "batch_id": batch_id, "state": board_state, "golden": golden, "cursor": cursor, "limit": clamp_limit(limit)},
    )
    if not reply.ok:
        return from_reply(reply)
    body = reply.body or {}
    items = body.get("items") or []
    if not items:
        return ok("没有符合条件的均热板。放宽型号、批次或状态后再查。档案里没有等级和单板缺陷。", {"boards": []})
    shown = "、".join(str(item.get("serial_number")) for item in items[:8])
    return ok(f"符合条件，本次 {len(items)} 片：{shown}。", {"boards": items}, next_cursor=body.get("next_cursor"))


async def _board(c: Ctx, serial_number: str) -> dict:
    reply = await c.get(f"/products/{serial_number}")
    if not reply.ok:
        return from_reply(reply)
    board = reply.body or {}
    return ok(_board_text(board) + "。档案里没有等级、单板缺陷和真实热阻。", {"board": board})


async def _defect_kinds(c: Ctx) -> dict:
    reply = await c.get("/defect-kinds")
    if not reply.ok:
        return from_reply(reply)
    kinds = (reply.body or {}).get("kinds") or []
    text = "；".join(f"{item.get('kind')}：{item.get('phenomenon')}" for item in kinds if isinstance(item, dict))
    return ok(
        f"缺陷目录共 {len(kinds)} 种。{text}。",
        {"kinds": kinds},
        hints=["这是种类说明，不是某一片板的结论。"],
    )


async def _export(c: Ctx, limits_plan_id: str, version: int | None, batch_id: str | None) -> dict:
    reply = await c.get("/export/production", {"limits_plan_id": limits_plan_id, "version": version, "batch_id": batch_id})
    if not reply.ok:
        return from_reply(reply)
    body = reply.body or {}
    rows = body.get("data_rows", 0)
    version_text = f"版本 {version}" if version is not None else "未写版本，表头用该方案最新已发布版"
    detail = "前三行是列名、Upper Limited、Lower Limited。只含已完成且保留结果的记录。"
    if rows == 0:
        detail = "没有已完成且保留了结果的记录，所以表里只有表头。这不是导出失败。"
    return ok(f"已导出 {rows} 行生产结果。上限和下限来自方案 {limits_plan_id}，{version_text}。{detail}", body)
