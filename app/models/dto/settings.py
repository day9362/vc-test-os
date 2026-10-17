from pydantic import BaseModel, Field


class ClusterSettingsOut(BaseModel):
    base_url: str
    token: str
    timeout_s: float
    retries: int
    on_503: str


class SimSettingsOut(BaseModel):
    base_url: str
    speed: float
    use_ground_truth: bool


class SyncJobOut(BaseModel):
    key: str
    name: str
    api: str
    interval_s: int
    enabled: bool
    note: str


class StorageSettingsOut(BaseModel):
    dsn: str
    samples_days: int
    runs_days: int
    agg_5m: bool
    object_store: str


class AiSettingsOut(BaseModel):
    base_url: str
    api_key: str
    monthly_budget_m: float
    alert_pct: int
    models: dict[str, str]


class RuleSettingsOut(BaseModel):
    drift_c: float
    we_rules: list[str] = Field(default_factory=list)
    sentinel_as_data_anomaly: bool
    degraded_alarm: bool
    ack_timeout_min: int


class PlatformSettingsOut(BaseModel):
    source: str
    cluster: ClusterSettingsOut
    sim: SimSettingsOut
    jobs: list[SyncJobOut]
    storage: StorageSettingsOut
    ai: AiSettingsOut
    rules: RuleSettingsOut


class TestConnectionIn(BaseModel):
    source: str
    base_url: str
    token: str = ""


class TestConnectionOut(BaseModel):
    ok: bool
    latency_ms: int
    machines: int
    reachable: int
    server_version: str


class JobStatusItemOut(BaseModel):
    key: str
    last_at: int | None = None
    elapsed_ms: int | None = None
    failed: bool | None = None


class JobStatusOut(BaseModel):
    items: list[JobStatusItemOut]


class ScenarioOut(BaseModel):
    name: str
    text: str


class ScenarioListOut(BaseModel):
    items: list[ScenarioOut]


class FaultCatalogItemOut(BaseModel):
    kind: str
    layer: str
    alarms: bool


class FaultCatalogOut(BaseModel):
    items: list[FaultCatalogItemOut]


class ClockIn(BaseModel):
    speed: float


class ScenarioApplyIn(BaseModel):
    machine_id: str


class FaultInjectIn(BaseModel):
    machine_id: str
    kind: str
    slot_index: int | None = None


class SimActionOut(BaseModel):
    audit_id: str
    result: dict = Field(default_factory=dict)
