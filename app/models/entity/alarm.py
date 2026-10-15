from dataclasses import dataclass


@dataclass
class AlarmEntity:
    id: str
    time: int
    level: str
    machine_id: str
    slot_index: int | None
    source: str
    code: str
    message: str
    acked: bool
    acked_by: str | None = None
    acked_at: int | None = None


@dataclass
class AttributionEntity:
    alarm_id: str
    status: str
    category: str | None
    confidence: float | None
    summary: str
    evidence: list[str]
    suggestion: str
    model: str
    created_at: int
