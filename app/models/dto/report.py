from pydantic import BaseModel


class BatchStatOut(BaseModel):
    batch_id: str
    model: str
    count: int
    tested: int
    passed: int
    failed: int
    aborted: int
    plan_id: str
    plan_version: int
    machine_ids: list[str]
    started_at: int
    ended_at: int | None
    state: str
    rc_mean: float
    rc_sd: float
    top_fail: str
    top_fail_count: int = 0
    cpk_t01: float | None = None
    worst_machine_id: str = ""
    worst_machine_n: int = 0
    worst_machine_passed: int = 0


class ReportSummaryOut(BaseModel):
    tested: int
    passed: int
    failed: int
    aborted: int
    yield_rate: float
    rc_mean: float
    rc_sd: float
    cpk_t01: float
    usl_t01: float
    machine_count: int


class MachineYieldOut(BaseModel):
    machine_id: str
    n: int
    passed: int


class RcHistogramOut(BaseModel):
    edges: list[float]
    counts: dict[str, list[int]]


class FailParetoOut(BaseModel):
    item: str
    count: int


class DeltaProfileOut(BaseModel):
    items: list[str]
    mean: dict[str, list[float]]
    p95: list[float] | None
    limit: list[float | None]


class BatchCompareOut(BaseModel):
    batch_id: str
    yield_rate: float
    rc_mean: float


class ReportDataOut(BaseModel):
    batches: list[BatchStatOut]
    summary: ReportSummaryOut
    machine_yield: list[MachineYieldOut]
    rc_histogram: RcHistogramOut
    fail_pareto: list[FailParetoOut]
    delta_profile: DeltaProfileOut
    compare: list[BatchCompareOut]


class ReportExportIn(BaseModel):
    batch_ids: list[str]
    figure_ids: list[str] = []
    format: str = "pdf"


class ReportExportOut(BaseModel):
    url: str
