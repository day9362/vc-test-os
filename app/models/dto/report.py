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
    mean: dict[str, list[float | None]]
    p95: list[float | None] | None
    limit: list[float | None]


class BatchCompareOut(BaseModel):
    batch_id: str
    yield_rate: float
    rc_mean: float


class AmbientPointOut(BaseModel):
    batch_id: str
    serial: str
    ended_at: int
    machine_id: str = ""
    slot_index: int = 0
    value: float | None = None
    t01: float | None = None


class ReportDataOut(BaseModel):
    batches: list[BatchStatOut]
    summary: ReportSummaryOut
    machine_yield: list[MachineYieldOut]
    rc_histogram: RcHistogramOut
    ambient: list[AmbientPointOut] = []
    fail_pareto: list[FailParetoOut]
    delta_profile: DeltaProfileOut
    compare: list[BatchCompareOut]


class ExportBlock(BaseModel):
    kind: str
    text: str = ""
    title: str = ""
    png: str = ""
    columns: list[str] = []
    rows: list[list[str]] = []


class ReportExportIn(BaseModel):
    batch_ids: list[str]
    figure_ids: list[str] = []
    summary_lines: list[str] = []
    blocks: list[ExportBlock] = []
    format: str = "pdf"


class ReportExportOut(BaseModel):
    url: str


class ReportSummaryIn(BaseModel):
    batch_ids: list[str]
    mode: str = "single"


class ReportUsageOut(BaseModel):
    input: int
    output: int


class ReportNarrativeOut(BaseModel):
    lines: list[str]
    model: str
    usage: ReportUsageOut
    looked: str = ""


class LimitItemOut(BaseModel):
    item: str
    n: int
    mean: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    range: float | None = None
    std: float | None = None
    low: float | None = None
    high: float | None = None
    high_fail: int = 0
    low_fail: int = 0
    offset: str = ""
    margin_high: float | None = None
    margin_low: float | None = None
    cpk: float | None = None
    repeat_std: float | None = None
    retest_serials: int = 0
    retest_range: float | None = None
    trend: str = ""
    invalid: int = 0


class PairOut(BaseModel):
    left: str
    right: str
    r: float | None = None
    n: int = 0
    co_fail: int = 0


class ProcessNoteOut(BaseModel):
    serial_number: str
    item: str
    shape: str


class FailGroupOut(BaseModel):
    items: list[str]
    count: int


class AnalysisSliceOut(BaseModel):
    name: str
    aborted: int = 0
    discarded: int = 0
    invalid: int = 0
    items: list[LimitItemOut] = []
    correlations: list[PairOut] = []
    fail_groups: list[FailGroupOut] = []


class SlotCensusOut(BaseModel):
    slot: str
    tested: int
    passed: int


class BatchCensusOut(BaseModel):
    batch: str
    tested: int
    passed: int
    slots: list[SlotCensusOut] = []


class AnalysisOut(BaseModel):
    note: str = ""
    tested: int = 0
    aborted: int = 0
    discarded: int = 0
    invalid: int = 0
    fail_rank: list[FailParetoOut] = []
    fail_groups: list[FailGroupOut] = []
    overall: AnalysisSliceOut
    batches: list[AnalysisSliceOut] = []
    machines: list[AnalysisSliceOut] = []
    slots: list[AnalysisSliceOut] = []
    census: list[BatchCensusOut] = []
    process: list[ProcessNoteOut] = []


class FigurePanelOut(BaseModel):
    title: str = ""
    option: dict


class FigureIn(BaseModel):
    batch_ids: list[str]
    prompt: str = ""
    preset: str = ""


class FigureCreatedOut(BaseModel):
    figure_id: str


class FigureSummaryOut(BaseModel):
    scope: str
    columns: list[str]
    rows: list[list[str]]
    notes: list[str] = []


class FigureQuestionOut(BaseModel):
    text: str
    options: list[str] = []


class FigureTableOut(BaseModel):
    name: str = "所用数据"
    columns: list[str] = []
    rows: list[list[str]] = []


class FigureReplyIn(BaseModel):
    text: str = ""
    picks: list[str] = []


class FigureOut(BaseModel):
    figure_id: str
    status: str
    prompt: str
    title: str
    echarts_option: dict | None = None
    panels: list[FigurePanelOut] = []
    png_url: str | None = None
    code: str
    results: list[list[str]]
    summary: FigureSummaryOut | None = None
    table: FigureTableOut | None = None
    questions: list[FigureQuestionOut] = []
    note: str = ""
    usage: ReportUsageOut
    error: str | None = None
    step: str = ""
