def audit_note(actor: str, action: str, machine_id: str, request: dict | None, result: dict | None) -> str:
    who = actor or "未知用户"
    req = request or {}
    done = result or {}
    machine = machine_id or _text(req.get("machine_id"))
    where = f"{machine} " if machine else ""
    slot = req.get("slot_index")
    slot_text = f"{slot} 号槽" if slot is not None and slot != "" else ""

    if action == "settings.save":
        changes = req.get("changes") if isinstance(req.get("changes"), list) else []
        if changes:
            shown = "、".join(str(item) for item in changes[:8])
            tail = f" 等 {len(changes)} 项" if len(changes) > 8 else ""
            return f"{who} 修改了系统设置：{shown}{tail}"
        return f"{who} 保存了系统设置"
    if action == "sim.clock":
        speed = req.get("speed")
        targets = _join(req.get("machine_ids"))
        scope = f"{targets} 的" if targets else ""
        return f"{who} 把{scope}仿真倍率改为 ×{speed}"
    if action == "sim.scenario":
        return f"{who} 给 {machine or '机台'} 应用了仿真场景 {req.get('name') or ''}".rstrip()
    if action == "sim.fault":
        if machine and slot_text:
            place = f"{machine} 的 {slot_text}"
        else:
            place = machine or slot_text or "机台"
        return f"{who} 给 {place}注入了故障 {req.get('kind') or ''}".rstrip()
    if action == "compensation.write":
        mode = "叠加" if req.get("mode") == "add" else "覆盖"
        return f"{who} {mode}写入了 {machine or '机台'} 的通道补偿"
    if action == "report.export":
        batches = _join(req.get("batch_ids"))
        target = f"批次 {batches} 的" if batches else ""
        return f"{who} 导出了{target}报告"
    if action == "plan.dispatch":
        machines = _join(req.get("machine_ids"))
        plan = req.get("plan_id") or "方案"
        dest = f"到 {machines}" if machines else ""
        return f"{who} 把方案 {plan} 下发{dest}"
    if action == "production.start":
        return f"{who} 开始了连续生产"
    if action == "production.stop":
        batch = req.get("batch_id") or done.get("batch_id") or ""
        return f"{who} 停止了批次 {batch} 的连续生产".replace("批次  的", "的")
    if action == "batch.create":
        batch = done.get("batch_id") or ""
        count = done.get("count")
        extra = f" {batch}" if batch else ""
        pieces = f"，共 {count} 片" if count not in (None, "") else ""
        return f"{who} 创建了批次{extra}{pieces}"
    if action == "plan.publish":
        return f"{who} 发布了方案 {_name(req)}"
    if action == "plan.draft":
        return f"{who} 保存了方案草稿 {_name(req)}"
    if action == "plan.draft_update":
        return f"{who} 修改了方案草稿 {_name(req)}"
    if action == "plan.draft_delete":
        return f"{who} 删除了方案草稿 {req.get('plan_id') or ''}".rstrip()
    if action == "plan.from_text":
        return f"{who} 用一句话生成了方案草稿"
    if action == "alarm.ack":
        return f"{who} 确认了{where}告警 {req.get('alarm_id') or ''}".rstrip()
    if action == "alarm.unack":
        return f"{who} 取消确认了{where}告警 {req.get('alarm_id') or ''}".rstrip()
    if action == "alarm.ack_all":
        count = done.get("updated")
        extra = f"，共 {count} 条" if count not in (None, "") else ""
        return f"{who} 确认了全部未确认告警{extra}"
    if action == "alarm.attribution":
        return f"{who} 重新归因了{where}告警 {req.get('alarm_id') or ''}".rstrip()
    if action == "slot.load":
        serial = req.get("serial_number") or "单板"
        return f"{who} 把 {serial} 装入 {machine or '机台'} 的 {slot_text or '槽位'}"
    if action == "slot.start":
        return f"{who} 启动了 {machine or '机台'} 的 {slot_text or '槽位'}"
    if action == "slot.abort":
        return f"{who} 中止了 {machine or '机台'} 的 {slot_text or '槽位'}"
    if action == "slot.clear_error":
        return f"{who} 清除了 {machine or '机台'} 的 {slot_text or '槽位'} 错误"
    if action == "machine.power_on":
        return f"{who} 给 {machine or '机台'} 上电"
    if action == "machine.power_off":
        return f"{who} 关闭了 {machine or '机台'}"
    if action == "machine.reset":
        return f"{who} 复位了 {machine or '机台'}"
    if action == "machine.maintenance":
        verb = "进入" if req.get("on") else "退出"
        return f"{who} 让 {machine or '机台'} {verb}维修"
    if action == "product.requeue":
        return f"{who} 把单板 {req.get('serial_number') or ''} 重新排队".rstrip()
    return f"{who} 执行了 {action or '写操作'}"


def _name(req: dict) -> str:
    return str(req.get("name") or req.get("plan_id") or "").strip()


def _text(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _join(value: object) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value if item not in (None, ""))
    return _text(value)
