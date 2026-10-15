from sqlalchemy import BigInteger, Boolean, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class AlarmOrm(Base):
    __tablename__ = "alarms"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    time: Mapped[int] = mapped_column(BigInteger, index=True)
    level: Mapped[str] = mapped_column(String(16))
    machine_id: Mapped[str] = mapped_column(String(16), index=True)
    slot_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(256))
    acked: Mapped[bool] = mapped_column(Boolean, default=False)
    acked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acked_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AttributionOrm(Base):
    __tablename__ = "alarm_attributions"

    alarm_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(String(512), default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    suggestion: Mapped[str] = mapped_column(String(512), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[int] = mapped_column(BigInteger)


class AuditOrm(Base):
    __tablename__ = "audit_logs"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    time: Mapped[int] = mapped_column(BigInteger, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    machine_id: Mapped[str] = mapped_column(String(16), default="")
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class AiCallOrm(Base):
    __tablename__ = "ai_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    time: Mapped[int] = mapped_column(BigInteger, index=True)
    module: Mapped[str] = mapped_column(String(32))
    user: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    ref: Mapped[dict] = mapped_column(JSON, default=dict)
