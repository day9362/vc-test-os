from sqlalchemy import BigInteger, Boolean, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class RunOrm(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(16), index=True)
    slot_index: Mapped[int] = mapped_column(Integer)
    serial_number: Mapped[str] = mapped_column(String(128), default="")
    plan_id: Mapped[str] = mapped_column(String(64))
    plan_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fail_items: Mapped[list] = mapped_column(JSON, default=list)
    keep_result: Mapped[bool] = mapped_column(Boolean, default=True)
    rc: Mapped[float | None] = mapped_column(Float, nullable=True)
    dt01: Mapped[float | None] = mapped_column(Float, nullable=True)
    batch_id: Mapped[str] = mapped_column(String(128), default="")
    ended_at: Mapped[int] = mapped_column(BigInteger, index=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class RunSampleOrm(Base):
    __tablename__ = "run_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    t_s: Mapped[float] = mapped_column(Float)
    t0: Mapped[float] = mapped_column(Float)
    t1: Mapped[float] = mapped_column(Float)
    ta: Mapped[float] = mapped_column(Float)
    power_w: Mapped[float] = mapped_column(Float)


class Agg5mOrm(Base):
    __tablename__ = "agg_5m"

    bucket: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tests: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    aborted: Mapped[int] = mapped_column(Integer, default=0)
    rc_mean: Mapped[float] = mapped_column(Float, default=0)
    dt01_mean: Mapped[float] = mapped_column(Float, default=0)
