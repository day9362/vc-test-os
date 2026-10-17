from sqlalchemy import BigInteger, Boolean, Float, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class TestPlanOrm(Base):
    __tablename__ = "test_plans"
    __table_args__ = (UniqueConstraint("plan_id", "version", name="uq_plan_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128))
    start_temp_c: Mapped[float] = mapped_column(Float)
    duration_s: Mapped[int] = mapped_column(Integer)
    sample_period_s: Mapped[float] = mapped_column(Float)
    power_w: Mapped[float] = mapped_column(Float)
    force_g: Mapped[float] = mapped_column(Float)
    orientation: Mapped[int] = mapped_column(Integer)
    overtemp_c: Mapped[float] = mapped_column(Float)
    ambient_low_c: Mapped[float] = mapped_column(Float)
    ambient_high_c: Mapped[float] = mapped_column(Float)
    limits: Mapped[list] = mapped_column(JSON, default=list)
    author: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))
    draft: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[int] = mapped_column(BigInteger)
