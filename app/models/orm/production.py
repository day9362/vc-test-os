from sqlalchemy import BigInteger, Boolean, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class ProductModelOrm(Base):
    __tablename__ = "product_models"

    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    resistance_mean: Mapped[float] = mapped_column(Float, default=0)
    resistance_sd: Mapped[float] = mapped_column(Float, default=0)
    power_w: Mapped[float] = mapped_column(Float, default=0)


class BatchRecordOrm(Base):
    __tablename__ = "batch_records"

    batch_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    count: Mapped[int] = mapped_column(Integer, default=0)
    defect_ratio: Mapped[float] = mapped_column(Float, default=0)
    batch_factor: Mapped[float] = mapped_column(Float, default=1)
    remaining: Mapped[int] = mapped_column(Integer, default=0)
    remaining_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    tested: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    aborted: Mapped[int] = mapped_column(Integer, default=0)
    plan_id: Mapped[str] = mapped_column(String(64), default="")
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
    machine_ids: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[int] = mapped_column(BigInteger, default=0)
    ended_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="")
    rc_mean: Mapped[float] = mapped_column(Float, default=0)
    rc_sd: Mapped[float] = mapped_column(Float, default=0)
    top_fail: Mapped[str] = mapped_column(String(64), default="")
    eta_s: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ProductionOrm(Base):
    __tablename__ = "production_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    batch_id: Mapped[str] = mapped_column(String(128), default="")
    queue_remaining: Mapped[int] = mapped_column(Integer, default=0)
    plan_id: Mapped[str] = mapped_column(String(64), default="")
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
