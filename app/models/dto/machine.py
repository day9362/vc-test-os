from pydantic import BaseModel


class CapabilityOut(BaseModel):
    temp_channels: list[str]
    force_channels: list[str]
    duration_low_s: float
    duration_high_s: float
    power_low_w: float
    power_high_w: float
    force_low_g: float
    force_high_g: float


class SlotOut(BaseModel):
    index: int
    phase: str
    serial_number: str | None
    tests_done: int
    last_error: str
    power_w: float
    vacuum_kpa: float
    t0: float
    t1: float
    ta: float
    progress: float
    run_id: str | None


class YieldRecentOut(BaseModel):
    n: int
    passed: int


class MachineOut(BaseModel):
    machine_id: str
    serial: str
    fixture: str
    holder: str
    thermal_boards: str
    plc: str
    firmware: str
    slot_count: int
    status: str
    comm_status: str
    comm_note: str
    speed: float
    room_temp_c: float
    alarm: str
    plan_id: str | None
    plan_version: int | None
    capability: CapabilityOut
    slots: list[SlotOut]
    last_sync_at: int
    yield_recent: YieldRecentOut


class CurvePointOut(BaseModel):
    t_s: float
    T0: float
    T1: float
    Ta: float
    power_w: float


class MachineActionOut(BaseModel):
    audit_id: str
    machine_id: str
    status: str


class SlotCurveOut(BaseModel):
    run_id: str | None
    plan_id: str | None
    plan_version: int | None
    duration_s: int | None
    points: list[CurvePointOut]
    deltas: dict[str, float]
