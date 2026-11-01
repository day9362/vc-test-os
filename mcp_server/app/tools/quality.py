from typing import Literal

from app.approval import Preview, guarded, pick
from app.config import settings
from app.models import ChannelValue
from app.result import fail, from_reply, missing, ok
from app.state import Ctx, ctx
from app.text import join_ids

QualityAction = Literal[
    "ack",
    "unack",
    "ack_all",
    "rerun_attribution",
    "apply_compensation",
    "report_summary",
    "report_figure",
    "report_export",
]


async def vc_quality(
    action: QualityAction,
    alarm_ids: list[str] | None = None,
    alarm_id: str | None = None,
    machine_id: str | None = None,
    mode: Literal["add", "set"] | None = None,
    items: list[ChannelValue] | None = None,
    batch_ids: list[str] | None = None,
    prompt: str | None = None,
    figure_id: str | None = None,
    figure_ids: list[str] | None = None,
    summary_lines: list[str] | None = None,
    confirm_id: str | None = None,
    approval: str | None = None,
) -> dict:
    """VC-TestOS 质量处置（写）：告警处理、通道补偿、批次报告。

    action:
    - ack / unack：确认或取消确认告警，要 alarm_ids。直接执行。
    - ack_all：确认全部未确认告警。需批准。
    - rerun_attribution：重新归因一条告警，要 alarm_id。直接执行。
    - apply_compensation：写入 machine_id 的通道补偿，要 mode 和 items[{channel, value}]。mode=add 在当前值上叠加，set 直接设为该值。
      只影响之后的新测试。需批准。先用 vc_data calibration 看当前值和建议。
    - report_summary：生成批次报告结论，要 batch_ids。直接执行。
    - report_figure：给 batch_ids 和 prompt 生成图表（异步，返回 figure_id）；只给 figure_id 时查进度。直接执行。
    - report_export：导出 PDF 报告，要 batch_ids，可带 figure_ids、summary_lines。直接执行。
    confirm_id、approval 只由页面批准后使用，不要自己填写。
    """
    c = ctx()
    args = pick(
        {
            "alarm_ids": alarm_ids,
            "alarm_id": alarm_id,
            "machine_id": machine_id,
            "mode": mode,
            "items": items,
            "batch_ids": batch_ids,
            "prompt": prompt,
            "figure_id": figure_id,
            "figure_ids": figure_ids,
            "summary_lines": summary_lines,
        }
    )

    async def preview():
        return await _preview(c, action, args)

    async def execute(values: dict, idem: str | None) -> dict:
        return await _run(c, action, values, idem)

    return await guarded(c, "vc_quality", action, args, confirm_id=confirm_id, approval=approval, preview=preview, execute=execute)


async def _preview(c: Ctx, action: str, args: dict):
    if action == "ack_all":
        reply = await c.get("/alarms", {"acked": False, "limit": 200})
        if not reply.ok:
            return from_reply(reply)
        body = reply.body or {}
        count = len(body.get("items") or [])
        if count == 0:
            return fail("现在没有未确认的告警。", "CONFLICT", status=409)
        shown = f"{count} 条以上" if body.get("next_cursor") else f"{count} 条"
        return Preview(f"确认全部 {shown}未确认告警", ["确认后这些告警不再出现在未确认列表"])
    if action == "apply_compensation":
        mid, items = args.get("machine_id"), args.get("items") or []
        if not mid or not args.get("mode") or not items:
            return missing("machine_id", "mode", "items")
        reply = await c.get(f"/machines/{mid}/compensation")
        if not reply.ok:
            return from_reply(reply)
        now = {item.get("channel"): float(item.get("value") or 0) for item in (reply.body or {}).get("items") or []}
        effects = []
        for item in items:
            before = now.get(item["channel"], 0.0)
            after = before + float(item["value"]) if args["mode"] == "add" else float(item["value"])
            effects.append(f"{item['channel']}：{before:+.3f} → {after:+.3f} ℃")
        effects.append("只影响之后的新测试，已有记录不变")
        return Preview(f"写入 {mid} 的通道补偿（{join_ids([item['channel'] for item in items])}）", effects)
    return missing("action")


async def _run(c: Ctx, action: str, values: dict, idem: str | None) -> dict:
    if action in {"ack", "unack"}:
        ids = values.get("alarm_ids") or ([values["alarm_id"]] if values.get("alarm_id") else [])
        if not ids:
            return missing("alarm_ids")
        done, failed = [], []
        for alarm in ids:
            reply = await c.post(f"/alarms/{alarm}/{action}")
            (done if reply.ok else failed).append(alarm if reply.ok else {"alarm_id": alarm, "reason": reply.message or reply.code})
        verb = "已确认" if action == "ack" else "已取消确认"
        if not done:
            return fail(f"告警都没处理成功：{failed[0]['reason']}。", "CONFLICT", detail={"failed": failed})
        text = f"{len(done)} 条告警{verb}。" + (f"{len(failed)} 条没成功。" if failed else "")
        return ok(text, {"done": done, "failed": failed})
    if action == "ack_all":
        reply = await c.post("/alarms/ack-all", idem=idem)
        if not reply.ok:
            return from_reply(reply)
        return ok(f"已确认 {(reply.body or {}).get('updated', 0)} 条告警。", reply.body)
    if action == "rerun_attribution":
        if not values.get("alarm_id"):
            return missing("alarm_id")
        reply = await c.post(f"/alarms/{values['alarm_id']}/attribution", timeout=settings.vc_long_timeout_s)
        if not reply.ok:
            return from_reply(reply)
        body = reply.body or {}
        return ok(f"重新归因：{body.get('category') or body.get('status')}。{body.get('summary') or ''}", body)
    if action == "apply_compensation":
        body = {"mode": values.get("mode"), "compensation": values.get("items") or []}
        reply = await c.put(f"/machines/{values.get('machine_id')}/compensation", body, idem=idem)
        if not reply.ok:
            return from_reply(reply)
        return ok(f"{values.get('machine_id')} 的通道补偿已写入，之后的新测试生效。", reply.body)
    if action == "report_summary":
        if not values.get("batch_ids"):
            return missing("batch_ids")
        reply = await c.post("/reports/summary", {"batch_ids": values["batch_ids"]}, timeout=settings.vc_long_timeout_s)
        if not reply.ok:
            return from_reply(reply)
        lines = (reply.body or {}).get("lines") or []
        return ok("报告结论：" + " ".join(lines), reply.body)
    if action == "report_figure":
        if values.get("figure_id") and not values.get("prompt"):
            reply = await c.get(f"/reports/figures/{values['figure_id']}")
            if not reply.ok:
                return from_reply(reply)
            return ok(f"图表 {values['figure_id']} 状态：{(reply.body or {}).get('status')}。", reply.body)
        if not values.get("batch_ids") or not values.get("prompt"):
            return missing("batch_ids", "prompt")
        reply = await c.post("/reports/figures", {"batch_ids": values["batch_ids"], "prompt": values["prompt"]}, timeout=60)
        if not reply.ok:
            return from_reply(reply)
        fid = (reply.body or {}).get("figure_id")
        return ok(f"图表 {fid} 开始生成，稍后用 report_figure 带 figure_id 查进度。", reply.body)
    if action == "report_export":
        if not values.get("batch_ids"):
            return missing("batch_ids")
        body = {
            "batch_ids": values["batch_ids"],
            "figure_ids": values.get("figure_ids") or [],
            "summary_lines": values.get("summary_lines") or [],
            "format": "pdf",
        }
        reply = await c.post("/reports/export", body, timeout=settings.vc_long_timeout_s)
        if not reply.ok:
            return from_reply(reply)
        return ok(f"报告已导出：{(reply.body or {}).get('url')}", reply.body)
    return missing("action")
