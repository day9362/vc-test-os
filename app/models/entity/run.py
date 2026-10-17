from dataclasses import dataclass, field


@dataclass
class RunEntity:
    run_id: str
    machine_id: str
    slot_index: int
    serial_number: str
    plan_id: str
    plan_version: int
    status: str
    passed: bool | None
    fail_items: list[str]
    keep_result: bool
    rc: float | None
    dt01: float | None
    batch_id: str
    ended_at: int
    result: dict = field(default_factory=dict)
