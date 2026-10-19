from app.models.dto.production import IssueOut, ProductionIn

BUSY = {"PREHEATING", "WAITING_LOAD", "CLAMPING", "SAMPLING", "RECOVERING"}
OFFLINE = {"CREATED", "OFFLINE", "STOPPED"}


def precheck(
    body: ProductionIn,
    *,
    plan_found: bool,
    plan_power: float | None,
    limits: list[dict],
    model_power: float | None,
    remaining: int | None,
    batch_known: bool,
    machines: list[dict],
    sim_mode: bool,
) -> list[IssueOut]:
    issues: list[IssueOut] = []
    if body.batch_id and body.serial_numbers:
        issues.append(IssueOut(level="danger", field="batch_id", message="批次号和序列号只能留一个"))
    if not body.batch_id and not body.serial_numbers:
        issues.append(IssueOut(level="danger", field="batch_id", message="要指定批次号或序列号"))
    if not body.machine_ids:
        issues.append(IssueOut(level="danger", field="machine_ids", message="至少选择一台机台"))
    if not plan_found or plan_power is None:
        issues.append(IssueOut(level="danger", field="plan_id", message="方案不存在"))
    elif model_power is not None and abs(plan_power - model_power) >= 0.05:
        issues.append(IssueOut(
            level="danger",
            field="power_w",
            message=f"方案功率 {plan_power:g} W 与型号参考功率 {model_power:g} W 不一致",
        ))
    if plan_found and not any(item.get("item") == "power_w" and not item.get("skipped") for item in limits):
        issues.append(IssueOut(level="warn", field="power_w", message="方案未设置 power_w 判定项，功率异常不会被判不合格"))
    if body.batch_id:
        if not batch_known:
            issues.append(IssueOut(level="danger", field="batch_id", message="批次不存在"))
        elif remaining is None or remaining <= 0:
            issues.append(IssueOut(level="danger", field="batch_id", message="该批次没有状态为 NEW 的均热板"))
    known = {row["machine_id"]: row for row in machines}
    for machine_id in body.machine_ids:
        row = known.get(machine_id)
        if row is None:
            issues.append(IssueOut(level="danger", field="machine_ids", message=f"{machine_id} 不在当前机群里"))
            continue
        if row.get("comm_status") == "DISCONNECTED":
            issues.append(IssueOut(level="danger", field="machine_ids", message=f"{machine_id} 通信断开"))
        if row.get("status") == "MAINTENANCE":
            issues.append(IssueOut(level="danger", field="machine_ids", message=f"{machine_id} 维修中"))
        elif row.get("status") == "FAULT":
            issues.append(IssueOut(level="danger", field="machine_ids", message=f"{machine_id} 处于故障"))
        busy = any(slot.get("phase") in BUSY for slot in row.get("slots") or [])
        other = bool(row.get("plan_id")) and (row.get("plan_id") != body.plan_id or row.get("plan_version") != body.plan_version)
        if busy and other:
            issues.append(IssueOut(level="warn", field="machine_ids", message=f"{machine_id} 正在测量其它方案，开始后会被跳过"))
        if sim_mode and float(row.get("speed") or 0) < 1:
            issues.append(IssueOut(level="warn", field="machine_ids", message=f"{machine_id} 仿真倍率过低，进度会很慢"))
    return issues


def skip_reasons(body: ProductionIn, machines: list[dict]) -> list[tuple[str, str]]:
    known = {row["machine_id"]: row for row in machines}
    skipped = []
    for machine_id in body.machine_ids:
        row = known.get(machine_id)
        if row is None:
            continue
        busy = any(slot.get("phase") in BUSY for slot in row.get("slots") or [])
        other = bool(row.get("plan_id")) and (row.get("plan_id") != body.plan_id or row.get("plan_version") != body.plan_version)
        if busy and other:
            skipped.append((machine_id, "正在测量且方案不同"))
    return skipped


def needs_dispatch(row: dict, plan_id: str, plan_version: int) -> bool:
    if row.get("status") in OFFLINE:
        return True
    if row.get("plan_id") != plan_id or row.get("plan_version") != plan_version:
        return True
    return False
