from sqlalchemy import BigInteger, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class AgentSessionOrm(Base):
    __tablename__ = "agent_sessions"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    module: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(80), default="新对话")
    sdk_session_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger, index=True)


class AgentMessageOrm(Base):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text, default="")
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    module: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tokens: Mapped[list | None] = mapped_column(JSON, nullable=True)
    time: Mapped[int] = mapped_column(BigInteger)
