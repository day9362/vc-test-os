from sqlalchemy import BigInteger, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class ReportNarrativeOrm(Base):
    __tablename__ = "report_narratives"

    narrative_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(512), index=True)
    lines: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[int] = mapped_column(BigInteger, index=True)
