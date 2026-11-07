"""判定与告警：读系统设置里保存的规则，并按 Western Electric 规则看通道温差。"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repo.settings_repo import SettingsRepo

WE_RULES = ("WE-1", "WE-2", "WE-3", "WE-4")
DEFAULT_WE = ("WE-1", "WE-2", "WE-4")
ESCALATION = {"minor": "major", "major": "critical"}
ESCALATED_MARK = "，超时未确认已升级"


@dataclass(frozen=True)
class AlarmRules:
    drift_c: float
    we_rules: tuple[str, ...]
    sentinel_as_data_anomaly: bool
    degraded_alarm: bool
    ack_timeout_min: int


def alarm_rules_from(payload: dict | None) -> AlarmRules:
    rules = (payload or {}).get("rules") or {}
    raw_drift = rules.get("drift_c", settings.drift_c)
    try:
        drift_c = float(raw_drift)
    except (TypeError, ValueError):
        drift_c = settings.drift_c
    selected = rules.get("we_rules", list(DEFAULT_WE))
    if not isinstance(selected, list):
        selected = list(DEFAULT_WE)
    we_rules = tuple(item for item in selected if item in WE_RULES)
    return AlarmRules(
        drift_c=drift_c,
        we_rules=we_rules,
        sentinel_as_data_anomaly=_flag(rules, "sentinel_as_data_anomaly", True),
        degraded_alarm=_flag(rules, "degraded_alarm", settings.degraded_alarm),
        ack_timeout_min=_minutes(rules.get("ack_timeout_min", 15)),
    )


async def load_alarm_rules(session: AsyncSession) -> AlarmRules:
    row = await SettingsRepo(session).get_or_create()
    return alarm_rules_from(row.payload)


def matched_we_rules(samples: list[float], enabled: tuple[str, ...]) -> list[str]:
    """samples 从新到旧。中心线和标准差用最新 8 点之前的历史。"""
    chosen = set(enabled)
    if not chosen:
        return []
    baseline = samples[8:]
    if len(baseline) < 8:
        return []
    center = sum(baseline) / len(baseline)
    variance = sum((value - center) ** 2 for value in baseline) / (len(baseline) - 1)
    sigma = variance ** 0.5
    hit: list[str] = []
    if "WE-1" in chosen and sigma > 0 and abs(samples[0] - center) > 3 * sigma:
        hit.append("WE-1")
    if "WE-2" in chosen and sigma > 0 and _same_side(samples[:3], center, 2 * sigma, 2):
        hit.append("WE-2")
    if "WE-3" in chosen and sigma > 0 and _same_side(samples[:5], center, sigma, 4):
        hit.append("WE-3")
    if "WE-4" in chosen and _one_side(samples[:8], center):
        hit.append("WE-4")
    return hit


def we_message(rule: str, latest: float) -> str:
    if rule == "WE-1":
        return f"T0-T1 最新点 {latest:+.3f} ℃，超出中心线 3 倍标准差"
    if rule == "WE-2":
        return "T0-T1 近 3 点里有 2 点在同一侧超出中心线 2 倍标准差"
    if rule == "WE-3":
        return "T0-T1 近 5 点里有 4 点在同一侧超出中心线 1 倍标准差"
    return "T0-T1 连续 8 点在中心线同一侧"


def escalate_alarm(alarm, now: int, timeout_min: int) -> bool:
    """未确认超过设定分钟数时，级别升一档，并只升一次。"""
    if timeout_min <= 0 or alarm.acked:
        return False
    nxt = ESCALATION.get(alarm.level)
    if nxt is None or ESCALATED_MARK in (alarm.message or ""):
        return False
    if now - int(alarm.time) < timeout_min * 60_000:
        return False
    alarm.level = nxt
    note = ESCALATED_MARK
    alarm.message = f"{alarm.message or ''}{note}"[:256]
    return True


def _flag(rules: dict, key: str, default: bool) -> bool:
    if key not in rules:
        return default
    return bool(rules[key])


def _minutes(value: object) -> int:
    try:
        minutes = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 15
    return max(0, minutes)


def _same_side(window: list[float], center: float, limit: float, need: int) -> bool:
    if len(window) < need:
        return False
    high = sum(1 for value in window if value - center > limit)
    low = sum(1 for value in window if center - value > limit)
    return high >= need or low >= need


def _one_side(window: list[float], center: float) -> bool:
    if len(window) < 8:
        return False
    return all(value > center for value in window) or all(value < center for value in window)
