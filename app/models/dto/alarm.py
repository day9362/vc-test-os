from pydantic import BaseModel, Field


class AlarmOut(BaseModel):
    id: str
    time: int
    level: str
    machine_id: str
    slot_index: int | None = None
    source: str
    code: str
    message: str
    acked: bool
    acked_by: str | None = None
    acked_at: int | None = None


class AlarmPageOut(BaseModel):
    items: list[AlarmOut]
    next_cursor: str | None


class AlarmActionOut(BaseModel):
    alarm: AlarmOut
    audit_id: str


class AckAllOut(BaseModel):
    updated: int
    audit_id: str


class AttributionOut(BaseModel):
    alarm_id: str
    status: str
    category: str | None = None
    confidence: float | None = None
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)
    suggestion: str = ""
    model: str = ""
    created_at: int
