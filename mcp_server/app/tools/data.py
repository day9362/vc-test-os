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
) -> dict:
    """VC-TestOS 历史数据与目录（只读）。用于跨批次分析、失败原因定位、查方案和补偿。良率只按测试记录算，不用批次的缺陷比例。

    action:
    - runs：测试记录列表。可按 machine_id、batch_id、passed、status（RUNNING/DONE/ABORTED）、q、时间（window 或 from_ms/to_ms）筛选。
    - run：一条记录的判定项和失败项，要 run_id。detail=true 附带采样数据。
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
    - sim_catalog：仿真场景和可注入的故障种类（仅仿真数据源）。
    """
    c = ctx()
    if action == "runs":
        return await _runs(c, machine_id, batch_id, passed, status, q, window, from_ms, to_ms, cursor, limit)
    if action == "run":
        if not run_id:
            return missing("run_id")
        return await _run(c, run_id, detail)
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


async def _run(c: Ctx, run_id: str, detail: bool) -> dict:
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
        samples = await c.get(f"/runs/{run_id}/samples")
        data["samples"] = samples.body if samples.ok else None
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
