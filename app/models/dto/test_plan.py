from pydantic import BaseModel, Field


class LimitIn(BaseModel):
    item: str
    low: float | None = None
    high: float | None = None
    unit: str = ""
    skipped: bool = False


class PlanBody(BaseModel):
    name: str
    start_temp_c: float
    duration_s: int
    sample_period_s: float
    power_w: float
    force_g: float
    orientation: int
    overtemp_c: float
    ambient_low_c: float
    ambient_high_c: float
    limits: list[LimitIn] = Field(default_factory=list)


class PlanOut(PlanBody):
    plan_id: str
    version: int


class PlanMetaOut(BaseModel):
    plan_id: str
    versions: list[int]
    updated_at: int
    author: str
    source: str
    draft: bool


class PlanItemOut(BaseModel):
    plan: PlanOut
    meta: PlanMetaOut


class PublishIn(PlanBody):
    plan_id: str | None = None


class PublishOut(BaseModel):
    plan_id: str
    version: int
    audit_id: str


class DraftOut(PlanItemOut):
    audit_id: str


class DeleteOut(BaseModel):
    audit_id: str


class IssueOut(BaseModel):
    level: str
    field: str | None = None
    message: str


class ValidateOut(BaseModel):
    ok: bool
    issues: list[IssueOut]


class FromTextIn(BaseModel):
    text: str


class UsageOut(BaseModel):
    input: int
    output: int


class FromTextOut(BaseModel):
    plan: PlanOut
    meta: PlanMetaOut
    notes: list[str]
    usage: UsageOut
    audit_id: str
