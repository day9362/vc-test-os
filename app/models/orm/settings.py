from sqlalchemy import BigInteger, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base


class SettingsOrm(Base):
    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[int] = mapped_column(BigInteger)
