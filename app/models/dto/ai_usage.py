from pydantic import BaseModel, Field


class AiModuleOut(BaseModel):
    id: str
    name: str
    where: str
    desc: str
    model: str
    trigger: str


class UsageMonthOut(BaseModel):
    used: int
    budget: int
    alert_pct: int
    paused: bool


class UsageModuleOut(BaseModel):
    module: str
    model: str
    calls: int
    input: int
    output: int
    total: int
    cost_cny: float


class UsageSummaryOut(BaseModel):
    days: int
    total: int
    input: int
    output: int
    calls: int
    cost_cny: float
    month: UsageMonthOut
    by_module: list[UsageModuleOut]


class UsageDayOut(BaseModel):
    ts: int
    by_module: dict[str, int]


class AiCallOut(BaseModel):
    id: str
    time: int
    module: str
    user: str
    model: str
    input: int
    output: int
    latency_ms: int
    ok: bool
    ref: dict = Field(default_factory=dict)


class AiCallPageOut(BaseModel):
    items: list[AiCallOut]
    next_cursor: str | None
