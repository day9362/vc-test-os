from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class TenantOrm(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


class UserOrm(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(160))
    tenant_id: Mapped[str] = mapped_column(String(64), default="line-a")
