from sqlalchemy import BigInteger, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class ReportFigureOrm(Base):
    __tablename__ = "report_figures"

    figure_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(512), index=True)
    batch_ids: Mapped[list] = mapped_column(JSON, default=list)
    prompt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="running")
    title: Mapped[str] = mapped_column(String(80), default="")
    step: Mapped[str] = mapped_column(String(80), default="")
    echarts_option: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    png_name: Mapped[str] = mapped_column(String(80), default="")
    code: Mapped[str] = mapped_column(Text, default="")
    results: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, index=True)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
