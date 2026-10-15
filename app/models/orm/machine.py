from sqlalchemy import BigInteger, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class MachineOrm(Base):
    __tablename__ = "machines"

    machine_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    serial: Mapped[str] = mapped_column(String(64))
    fixture: Mapped[str] = mapped_column(String(64))
    holder: Mapped[str] = mapped_column(String(64))
    thermal_boards: Mapped[str] = mapped_column(String(128))
    plc: Mapped[str] = mapped_column(String(16))
    firmware: Mapped[str] = mapped_column(String(64))
    slot_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    comm_status: Mapped[str] = mapped_column(String(32))
    comm_note: Mapped[str] = mapped_column(String(128), default="")
    speed: Mapped[float] = mapped_column(Float, default=1)
    room_temp_c: Mapped[float] = mapped_column(Float)
    alarm: Mapped[str] = mapped_column(String(256), default="")
    plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capability: Mapped[dict] = mapped_column(JSON)
    last_sync_at: Mapped[int] = mapped_column(BigInteger)


class SlotOrm(Base):
    __tablename__ = "slots"
    __table_args__ = (UniqueConstraint("machine_id", "index", name="uq_slot_machine_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.machine_id"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(32))
    serial_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tests_done: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(256), default="")
    power_w: Mapped[float] = mapped_column(Float, default=0)
    vacuum_kpa: Mapped[float] = mapped_column(Float, default=0)
    t0: Mapped[float] = mapped_column(Float, default=0)
    t1: Mapped[float] = mapped_column(Float, default=0)
    ta: Mapped[float] = mapped_column(Float, default=0)
    progress: Mapped[float] = mapped_column(Float, default=0)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
