from typing import Literal

from app.approval import Preview, guarded, pick
from app.config import settings
from app.models import PlanInput
from app.result import bad, fail, from_reply, missing, ok
from app.state import Ctx, ctx
from app.tools.data import vc_data

PlanAction = Literal["plans", "plan", "from_text", "validate", "save_draft", "delete_draft", "publish"]


async def run_plan(
    action: str,
    text: str | None = None,
    plan: PlanInput | None = None,
    plan_id: str | None = None,
    version: int | None = None,
    machine_ids: list[str] | None = None,
    confirm_id: str | None = None,
    approval: str | None = None,
    *,
    tool: str,
) -> dict:
    """VC-TestOS 测试方案的生成、校验、保存和发布（写）。查方案用 vc_data 的 plans / plan。

    取值：2.5 W 常配 100 g，3.5 W 常配 120 g；时长 1–600 秒；功率 0.1–10 W；压紧力 20–300 g。判定项温差写 Temp_T0-T1。

    action:
    - from_text：把自然语言整理成方案草稿，要 text。直接执行。
    - validate：校验 plan 是否合法，返回逐项问题。直接执行。
    - save_draft：保存 plan 为草稿；带 plan_id 表示更新这份草稿。直接执行。
    - delete_draft：删除草稿，要 plan_id。需批准。
    - publish：把 plan 发布为新版本（带 plan_id 表示在该方案下加版本），会先自动校验。需要用户在页面批准。发布不会自动下发到机台。
    - dispatch：把已发布的 plan_id 和 version 装到 machine_ids，不开始测试。需批准。一台失败则整次不算成功，已经装上的不要再发。
    判定项温差写成 Temp_T0-T1，不是 T0-T1。时长 1–600 秒，功率 0.1–10 W，压紧力 20–300 g。同意一次只覆盖这一次。
    confirm_id、approval 只由页面批准后使用，不要自己填写。
    """
    c = ctx()
    args = pick({"text": text, "plan": plan, "plan_id": plan_id, "version": version, "machine_ids": machine_ids})

    async def preview():
        if action == "delete_draft":
            return _delete_preview(args)
        if action == "dispatch":
            return await _dispatch_preview(c, args)
        return await _publish_preview(c, args)

    async def execute(values: dict, idem: str | None) -> dict:
        return await _run(c, action, values, idem)

    return await guarded(c, tool, action, args, confirm_id=confirm_id, approval=approval, preview=preview, execute=execute)


async def vc_plan(
    action: PlanAction,
    text: str | None = None,
    plan: PlanInput | None = None,
    plan_id: str | None = None,
    version: int | None = None,
    q: str | None = None,
    draft: bool | None = None,
    detail: bool = False,
    cursor: str | None = None,
    limit: int = 20,
    confirm_id: str | None = None,
    approval: str | None = None,
) -> dict:
    """VC-TestOS 测试方案。查询、起草、校验、保存、删除、发布都是这个工具的 action。上到机台用 vc_machine 的 dispatch。

    取值：2.5 W 常配 100 g，3.5 W 常配 120 g。时长 1–600 秒，功率 0.1–10 W，压紧力 20–300 g。判定项温差写 Temp_T0-T1。

    action:
    - plans：方案列表。q 按名称或编号，draft=true 只看草稿，false 只看已发布。
    - plan：方案详情，要 plan_id，可给 version。
    - from_text：把自然语言 text 整理成草稿。直接执行。
    - validate：校验 plan。直接执行。
    - save_draft：保存 plan；带 plan_id 表示更新这份草稿。直接执行。
    - delete_draft：删除草稿，要 plan_id。需批准。
    - publish：把 plan 发布为新版本（带 plan_id 表示在该方案下加版本），会先自动校验。需批准。发布不会自动装到机台。
    confirm_id、approval 只由页面批准后使用，不要自己填写。
    """
    if action in {"plans", "plan"}:
        return await vc_data(action, plan_id=plan_id, version=version, q=q, draft=draft, detail=detail, cursor=cursor, limit=limit)
    if action == "dispatch":
        return bad("上方案用 vc_machine，action 填 dispatch。", "给出 plan_id、version 和 machine_ids。")
    return await run_plan(
        action,
        text=text,
        plan=plan,
        plan_id=plan_id,
        version=version,
        confirm_id=confirm_id,
        approval=approval,
        tool="vc_plan",
    )


async def _run(c: Ctx, action: str, values: dict, idem: str | None) -> dict:
    plan = values.get("plan")
    plan_id = values.get("plan_id")
    if action == "from_text":
        if not values.get("text"):
            return missing("text")
        reply = await c.post("/plan-drafts/from-text", {"text": values["text"]}, timeout=settings.vc_long_timeout_s)
        if not reply.ok:
            return from_reply(reply)
        body = reply.body or {}
        p = body.get("plan") or {}
        notes = body.get("notes") or []
        text = f"已生成草稿 {p.get('plan_id')}「{p.get('name')}」：{p.get('power_w')} W、{p.get('force_g')} g、{p.get('duration_s')} 秒。"
        return ok(text, body, hints=notes or None)
    if action == "validate":
        if not plan:
            return missing("plan")
        return await _validate(c, plan)
    if action == "save_draft":
        if not plan:
            return missing("plan")
        reply = await (c.put(f"/plan-drafts/{plan_id}", plan) if plan_id else c.post("/plan-drafts", plan))
        if not reply.ok:
            return from_reply(reply)
        saved = (reply.body or {}).get("plan") or {}
        return ok(f"草稿 {saved.get('plan_id')}「{saved.get('name')}」已保存。", reply.body)
    if action == "delete_draft":
        if not plan_id:
            return missing("plan_id")
        reply = await c.delete(f"/plan-drafts/{plan_id}")
        if not reply.ok:
            return from_reply(reply)
        return ok(f"草稿 {plan_id} 已删除。", reply.body)
    if action == "publish":
        if not plan:
            return missing("plan")
        body = {**plan, "plan_id": plan_id} if plan_id else plan
        reply = await c.post("/plans", body, idem=idem)
        if not reply.ok:
            return from_reply(reply)
        out = reply.body or {}
        return ok(f"方案 {out.get('plan_id')} v{out.get('version')} 已发布。尚未下发到机台。", out)
    if action == "dispatch":
        return await _dispatch(c, values, idem)
    return missing("action")


async def _validate(c: Ctx, plan: dict) -> dict:
    reply = await c.post("/plans/validate", plan)
    if not reply.ok:
        return from_reply(reply)
    body = reply.body or {}
    issues = body.get("issues") or []
    problems = [item for item in issues if item.get("level") not in {"ok", "info"}]
    if body.get("ok") and not problems:
        return ok("方案校验通过。", body)
    text = "方案校验有问题：" + "；".join(f"{item.get('field') or '整体'}：{item.get('message')}" for item in problems[:5]) + "。"
    return ok(text, body) if body.get("ok") else fail(text, "VALIDATION_ERROR", status=422, detail=body)


async def _publish_preview(c: Ctx, args: dict):
    plan = args.get("plan")
    if not plan:
        return missing("plan")
    checked = await _validate(c, plan)
    if not checked.get("ok"):
        return checked
    target = f"在 {args['plan_id']} 下发布新版本" if args.get("plan_id") else "发布为新方案"
    sentence = f"把方案「{plan.get('name')}」{target}（{plan.get('power_w')} W、{plan.get('force_g')} g、{plan.get('duration_s')} 秒）"
    return Preview(sentence, ["发布后机器上的方案还没变，要另外上方案才会装到机台"], precheck=checked.get("data"))


def _delete_preview(args: dict):
    plan_id = args.get("plan_id")
    if not plan_id:
        return missing("plan_id")
    return Preview(f"删除草稿 {plan_id}", ["只删除这份草稿，已发布的版本还在"])


async def _dispatch_preview(c: Ctx, args: dict):
    plan_id, version, machines = args.get("plan_id"), args.get("version"), args.get("machine_ids") or []
    if not plan_id or version is None or not machines:
        return missing("plan_id", "version", "machine_ids")
    reply = await c.get(f"/plans/{plan_id}", {"version": version})
    if not reply.ok:
        return from_reply(reply)
    fleet = await c.get("/machines")
    if not fleet.ok:
        return from_reply(fleet)
    known = {row.get("machine_id") for row in fleet.body or [] if isinstance(row, dict)}
    unknown = [mid for mid in machines if mid not in known]
    if unknown:
        return fail(f"没有这些机台：{'、'.join(unknown)}。", "NOT_FOUND", status=404)
    name = ((reply.body or {}).get("plan") or reply.body or {}).get("name") or plan_id
    return Preview(
        f"把方案 {name} {plan_id} v{version} 装到 {'、'.join(machines)}，先不开测",
        ["只更换这些机器上的方案，不开始连续生产"],
        args={"plan_id": plan_id, "version": version, "machine_ids": list(machines)},
    )


async def _dispatch(c: Ctx, values: dict, idem: str | None) -> dict:
    plan_id, version, machines = values.get("plan_id"), values.get("version"), values.get("machine_ids") or []
    if not plan_id or version is None or not machines:
        return missing("plan_id", "version", "machine_ids")
    reply = await c.post(
        "/plans/dispatch",
        {"plan_id": plan_id, "version": version, "machine_ids": machines},
        idem=idem,
    )
    if not reply.ok:
        return from_reply(reply)
    body = reply.body or {}
    succeeded = body.get("succeeded") or []
    failed = body.get("failed") or []
    if failed:
        done = "、".join(succeeded) if succeeded else "没有"
        missed = "；".join(f"{item.get('machine_id')}（{item.get('reason')}）" for item in failed)
        return fail(
            f"方案 {plan_id} v{version} 已装上 {done}。没装上：{missed}。",
            "PARTIAL",
            detail=body,
            hints=["已经装上的不要再发。再次批准会跳过已成功的，并重试没装上的。"],
        )
    return ok(f"已把 {plan_id} v{version} 装到 {'、'.join(succeeded)}。这些机器还没开始测试。", body)
