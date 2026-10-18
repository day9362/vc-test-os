import re

from app.models.dto.test_plan import PlanBody, UsageOut


def draft_from_text(text: str) -> tuple[PlanBody, list[str], UsageOut]:
    notes: list[str] = []
    power_match = re.search(r"([\d.]+)\s*[wW]", text)
    if power_match:
        power = float(power_match.group(1))
    elif re.search(r"HVP", text, re.I):
        power = 3.5
        notes.append("功率未写明，按 HVP 常用的 3.5 W 填写")
    else:
        power = 2.5
        notes.append("功率未写明，按 2.5 W 填写")
    if re.search(r"(\d+)\s*秒", text):
        duration = int(re.search(r"(\d+)\s*秒", text).group(1))
    elif re.search(r"(\d+)\s*分钟", text):
        duration = int(re.search(r"(\d+)\s*分钟", text).group(1)) * 60
    else:
        duration = 180
        notes.append("时长未写明，按 3 分钟填写")
    force_match = re.search(r"(\d+)\s*g", text)
    if force_match:
        force = float(force_match.group(1))
    else:
        force = 120 if power > 3 else 100
        notes.append("压紧力未说明，按该功率的常用配置填写")
    t01_match = re.search(r"T0-?T1[^\d]*([\d.]+)", text, re.I)
    t01 = float(t01_match.group(1)) if t01_match else (3.4 if power > 3 else 2.8)
    t1x_match = re.search(r"温差[^\d]*([\d.]+)", text)
    t1x = float(t1x_match.group(1)) if t1x_match else (4.8 if power > 3 else 4.0)
    orientation = 90 if re.search(r"90", text) else 0
    quick = duration <= 30
    power_limit = {"item": "power_w", "low": round(power - 0.1, 2), "high": round(power + 0.1, 2), "unit": "W", "skipped": False}
    if quick:
        limits = [power_limit]
        notes.append("快速检查只保留 power_w 判定项")
    else:
        limits = [{"item": "Temp_T0-T1", "low": 0, "high": t01, "unit": "℃", "skipped": False}]
        limits += [{"item": f"Temp_T1-T{index + 2}", "low": 0, "high": t1x, "unit": "℃", "skipped": index > 10} for index in range(13)]
        limits.append(power_limit)
        notes.append("T1-T13、T1-T14 两个边缘点按惯例设为跳过")
    notes.append("power_w 判定范围按 ±0.1 W 填写，起始温度 45 ℃、环境 23–27 ℃ 沿用产线默认值")
    body = PlanBody(
        name=(text.strip()[:18] or "未命名草稿"),
        start_temp_c=45,
        duration_s=duration,
        sample_period_s=1,
        power_w=power,
        force_g=force,
        orientation=orientation,
        overtemp_c=80,
        ambient_low_c=23,
        ambient_high_c=27,
        limits=limits,
    )
    usage = UsageOut(input=max(len(text), 1), output=len(notes) * 20)
    return body, notes, usage
