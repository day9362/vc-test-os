from typing import Literal

from app.approval import Preview, guarded, pick
from app.config import settings
from app.models import PlanInput
from app.result import fail, from_reply, missing, ok
from app.state import Ctx, ctx

PlanAction = Literal["from_text", "validate", "save_draft", "delete_draft", "publish"]


async def vc_plan(
    action: PlanAction,
    text: str | None = None,
    plan: PlanInput | None = None,
    plan_id: str | None = None,
    confirm_id: str | None = None,
    approval: str | None = None,
) -> dict:
    """VC-TestOS 测试方案的生成、校验、保存和发布（写）。查方案用 vc_data 的 plans / plan。

    取值：2.5 W 常配 100 g，3.5 W 常配 120 g；时长 1–600 秒；功率 0.1–10 W；压紧力 20–300 g。判定项温差写 Temp_T0-T1。

    action:
    - from_text：把自然语言整理成方案草稿，要 text。直接执行。
    - validate：校验 plan 是否合法，返回逐项问题。直接执行。
    - save_draft：保存 plan 为草稿；带 plan_id 表示更新这份草稿。直接执行。
    - delete_draft：删除草稿，要 plan_id。直接执行。
    - publish：把 plan 发布为新版本（带 plan_id 表示在该方案下加版本），会先自动校验。需要用户在页面批准。
    confirm_id、approval 只由页面批准后使用，不要自己填写。
    """
    c = ctx()
    args = pick({"text": text, "plan": plan, "plan_id": plan_id})

    async def preview():
        return await _publish_preview(c, args)

    async def execute(values: dict, idem: str | None) -> dict:
        return await _run(c, action, values, idem)

    return await guarded(c, "vc_plan", action, args, confirm_id=confirm_id, approval=approval, preview=preview, execute=execute)


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
        return ok(f"方案 {out.get('plan_id')} v{out.get('version')} 已发布。", out)
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
    return Preview(sentence, ["发布后可以下发到机台进行连续生产"], precheck=checked.get("data"))
