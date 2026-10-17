from app.models.dto.test_plan import IssueOut, PlanBody, ValidateOut

ALLOWED_ITEMS = [
    "Temp_Ta",
    "Temp_T0-T1",
    *[f"Temp_T1-T{index}" for index in range(2, 15)],
    *[f"F{index}" for index in range(1, 15)],
    "power_w",
]
ORIENTATIONS = {0, 90, 180, 270}
MODELS = (("tb158", 2.5), ("tb172", 2.5), ("tb179", 2.5), ("HVP1307G17-1", 3.5))
DEFAULT_CAPABILITY = {
    "duration_low_s": 1,
    "duration_high_s": 600,
    "power_low_w": 0.1,
    "power_high_w": 10,
    "force_low_g": 20,
    "force_high_g": 300,
}


def fleet_bounds(capabilities: list[dict]) -> dict[str, float]:
    rows = capabilities or [DEFAULT_CAPABILITY]
    return {
        "duration_low_s": max(float(row.get("duration_low_s", 1)) for row in rows),
        "duration_high_s": min(float(row.get("duration_high_s", 600)) for row in rows),
        "power_low_w": max(float(row.get("power_low_w", 0.1)) for row in rows),
        "power_high_w": min(float(row.get("power_high_w", 10)) for row in rows),
        "force_low_g": max(float(row.get("force_low_g", 20)) for row in rows),
        "force_high_g": min(float(row.get("force_high_g", 300)) for row in rows),
    }


def validate_plan(body: PlanBody, bounds: dict[str, float]) -> ValidateOut:
    issues: list[IssueOut] = []
    if not body.name.strip():
        issues.append(IssueOut(level="danger", field="name", message="方案名称不能为空"))
    if body.orientation not in ORIENTATIONS:
        issues.append(IssueOut(level="danger", field="orientation", message="方向只能是 0、90、180 或 270"))
    _range(issues, "duration_s", body.duration_s, bounds["duration_low_s"], bounds["duration_high_s"], "s")
    _range(issues, "power_w", body.power_w, bounds["power_low_w"], bounds["power_high_w"], "W")
    _range(issues, "force_g", body.force_g, bounds["force_low_g"], bounds["force_high_g"], "g")
    if body.ambient_low_c >= body.ambient_high_c:
        issues.append(IssueOut(level="danger", field="ambient_low_c", message="环境温度下限必须低于上限"))
    if body.overtemp_c - body.start_temp_c < 10:
        issues.append(IssueOut(level="warn", field="overtemp_c", message="超温保护距离起始温度不足 10 ℃，可能误触发"))
    seen: set[str] = set()
    power_rule = None
    for rule in body.limits:
        if rule.item not in ALLOWED_ITEMS:
            issues.append(IssueOut(level="danger", field="limits", message=f"判定项 {rule.item} 不在可选范围内"))
            continue
        if rule.item in seen:
            issues.append(IssueOut(level="danger", field="limits", message=f"判定项 {rule.item} 重复"))
        seen.add(rule.item)
        if rule.skipped:
            continue
        if rule.low is not None and rule.high is not None and rule.low >= rule.high:
            issues.append(IssueOut(level="danger", field=rule.item, message=f"{rule.item} 的下限必须低于上限"))
        if rule.item == "power_w":
            power_rule = rule
    if power_rule is None:
        issues.append(IssueOut(level="warn", field="power_w", message="没有启用的 power_w 判定项"))
    elif (power_rule.low is not None and body.power_w < power_rule.low) or (power_rule.high is not None and body.power_w > power_rule.high):
        issues.append(IssueOut(level="danger", field="power_w", message=f"加热功率 {body.power_w:g} W 不在 power_w 判定范围内"))
    matched = [name for name, power in MODELS if power == body.power_w]
    if matched:
        issues.append(IssueOut(level="ok", field="power_w", message=f"功率与 {'、'.join(matched)} 的参考功率一致"))
    else:
        nearest = min(MODELS, key=lambda item: abs(item[1] - body.power_w))
        issues.append(IssueOut(level="warn", field="power_w", message=f"功率 {body.power_w:g} W 与已登记型号不一致，最接近 {nearest[0]} 的 {nearest[1]:g} W"))
    return ValidateOut(ok=not any(issue.level == "danger" for issue in issues), issues=issues)


def _range(issues: list[IssueOut], field: str, value: float, low: float, high: float, unit: str) -> None:
    if value < low or value > high:
        issues.append(IssueOut(level="danger", field=field, message=f"{field} {value:g} 超出机台能力 {low:g}–{high:g} {unit}"))
