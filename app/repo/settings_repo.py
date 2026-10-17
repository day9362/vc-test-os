from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.models.orm.settings import SettingsOrm
from app.service.settings.defaults import default_payload


class SettingsRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self) -> SettingsOrm:
        row = await self.session.get(SettingsOrm, 1)
        if row is None:
            row = SettingsOrm(id=1, payload=default_payload(), updated_at=now_ms())
            self.session.add(row)
            await self.session.flush()
        return row

    async def save(self, payload: dict) -> SettingsOrm:
        row = await self.get_or_create()
        row.payload = payload
        row.updated_at = now_ms()
        await self.session.flush()
        return row
