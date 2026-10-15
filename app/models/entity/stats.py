from dataclasses import dataclass


@dataclass
class KpiEntity:
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
    prev_tests: int
    prev_yield_rate: float


@dataclass
class Agg5mEntity:
    bucket: int
    tests: int
    passed: int
    failed: int
    aborted: int
    rc_mean: float
    dt01_mean: float


@dataclass
class PipelineStep:
    text: str
    state: str
