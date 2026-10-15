from pydantic import BaseModel


class KpiPrevOut(BaseModel):
    tests: int
    yield_rate: float


class KpiOut(BaseModel):
    online: int
    total: int
    busy_slots: int
    error_slots: int
    slot_total: int
    tests: int
    yield_rate: float
    rc_mean: float
    open_alarms: int
    critical_alarms: int
    prev: KpiPrevOut


class Agg5mOut(BaseModel):
    bucket: int
    tests: int
    passed: int
    failed: int
    aborted: int
    rc_mean: float
    dt01_mean: float


class AnomalyTrendOut(BaseModel):
    hours: list[int]
    series: dict[str, list[int]]


class RcBiasItemOut(BaseModel):
    machine_id: str
    bias: float


class RcBiasOut(BaseModel):
    median: float
    items: list[RcBiasItemOut]


class PipelineStepOut(BaseModel):
    text: str
    state: str


class PipelineOut(BaseModel):
    gen: PipelineStepOut
    check: PipelineStepOut
    dispatch: PipelineStepOut
    collect: PipelineStepOut
    anomaly: PipelineStepOut
    calib: PipelineStepOut
    report: PipelineStepOut
