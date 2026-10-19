from app.core.config import settings
from app.models.dto.compensation import ChannelBiasItemOut, ChannelBiasOut

GOLDEN_MODEL = "HVP1307G17-1"
GOLDEN_SAMPLES = 10
SENTINELS = {99999.0, 9999.0}


def is_golden(serial: str, batch_id: str) -> bool:
    text = f"{serial or ''} {batch_id or ''}"
    return GOLDEN_MODEL in text


def temps_of(result: dict | None) -> dict[str, float]:
    if not isinstance(result, dict):
        return {}
    raw = result.get("temps")
    pairs: list[tuple[object, object]] = []
    if isinstance(raw, dict):
        pairs = list(raw.items())
    elif isinstance(raw, list):
        pairs = [(item.get("channel"), item.get("value")) for item in raw if isinstance(item, dict)]
    out: dict[str, float] = {}
    for name, value in pairs:
        if not isinstance(name, str) or not name:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number in SENTINELS:
            continue
        out[name] = number
    return out


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _channel_key(name: str) -> tuple:
    if name == "Ta":
        return (1, 0, name)
    if name.startswith("T") and name[1:].isdigit():
        return (0, int(name[1:]), name)
    return (2, 0, name)


def estimate_channel_bias(machine_id: str, pieces: list[tuple[str, int, dict | None]]) -> ChannelBiasOut:
    grouped: dict[str, list[tuple[int, dict[str, float]]]] = {}
    for mid, ended_at, result in pieces:
        temps = temps_of(result)
        if not temps:
            continue
        bucket = grouped.setdefault(mid, [])
        if len(bucket) < GOLDEN_SAMPLES:
            bucket.append((ended_at, temps))
    means: dict[str, dict[str, float]] = {}
    for mid, rows in grouped.items():
        buckets: dict[str, list[float]] = {}
        for _ended, temps in rows:
            for channel, value in temps.items():
                buckets.setdefault(channel, []).append(value)
        if buckets:
            means[mid] = {channel: sum(vals) / len(vals) for channel, vals in buckets.items()}
    rows = grouped.get(machine_id, [])
    if machine_id not in means:
        return ChannelBiasOut(measured_at=0, golden_model=GOLDEN_MODEL, samples=0, threshold_c=settings.drift_c, items=[])
    items = []
    for channel in sorted(means[machine_id], key=_channel_key):
        votes = [row[channel] for row in means.values() if channel in row]
        items.append(ChannelBiasItemOut(channel=channel, value=round(means[machine_id][channel] - _median(votes), 3)))
    return ChannelBiasOut(
        measured_at=max(ended for ended, _temps in rows),
        golden_model=GOLDEN_MODEL,
        samples=len(rows),
        threshold_c=settings.drift_c,
        items=items,
    )
