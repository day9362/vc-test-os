from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class PlanDispatchOrm(Base):
    __tablename__ = "plan_dispatch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[str] = mapped_column(String(16), index=True)
    plan_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[int] = mapped_column(BigInteger)
    ended_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
