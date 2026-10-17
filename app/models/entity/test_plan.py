from dataclasses import dataclass


@dataclass
class LimitEntity:
    item: str
    low: float | None
    high: float | None
    unit: str
    skipped: bool


@dataclass
class PlanEntity:
    plan_id: str
    name: str
    version: int
    start_temp_c: float
    duration_s: int
    sample_period_s: float
    power_w: float
    force_g: float
    orientation: int
    overtemp_c: float
    ambient_low_c: float
    ambient_high_c: float
    limits: list[LimitEntity]
    author: str
    source: str
    draft: bool
    updated_at: int
    versions: list[int]
