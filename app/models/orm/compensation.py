from sqlalchemy import BigInteger, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class CompHistoryOrm(Base):
    __tablename__ = "compensation_history"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    time: Mapped[int] = mapped_column(BigInteger, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    machine_id: Mapped[str] = mapped_column(String(16), index=True)
    mode: Mapped[str] = mapped_column(String(8))
    compensation: Mapped[list] = mapped_column(JSON, default=list)
    audit_id: Mapped[str] = mapped_column(String(64), default="")
