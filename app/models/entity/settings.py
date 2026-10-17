from dataclasses import dataclass


@dataclass
class ClusterSettings:
    base_url: str
    token: str
    timeout_s: float
    retries: int
    on_503: str


@dataclass
class SimSettings:
    base_url: str
    speed: float
    use_ground_truth: bool


@dataclass
class SyncJob:
    key: str
    name: str
    api: str
    interval_s: int
    enabled: bool
    note: str


@dataclass
class StorageSettings:
    dsn: str
    samples_days: int
    runs_days: int
    agg_5m: bool
    object_store: str


@dataclass
class AiSettings:
    base_url: str
    api_key: str
    monthly_budget_m: float
    alert_pct: int
    models: dict[str, str]


@dataclass
class RuleSettings:
    drift_c: float
    we_rules: list[str]
    sentinel_as_data_anomaly: bool
    degraded_alarm: bool
    ack_timeout_min: int


@dataclass
class PlatformSettings:
    source: str
    cluster: ClusterSettings
    sim: SimSettings
    jobs: list[SyncJob]
    storage: StorageSettings
    ai: AiSettings
    rules: RuleSettings
    updated_at: int = 0
