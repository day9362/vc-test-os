from pydantic import BaseModel, Field


class RunOut(BaseModel):
    run_id: str
    machine_id: str
    slot_index: int
    serial_number: str
    plan_id: str
    plan_version: int
    status: str
    passed: bool | None
    fail_items: list[str] = Field(default_factory=list)
    keep_result: bool
    rc: float | None
    dt01: float | None
    batch_id: str
    ended_at: int


class RunDetailOut(RunOut):
    result: dict = Field(default_factory=dict)


class RunPageOut(BaseModel):
    items: list[RunOut]
    next_cursor: str | None
