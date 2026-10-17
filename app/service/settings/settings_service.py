from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dto.settings import PlatformSettingsOut
from app.repo.settings_repo import SettingsRepo
from app.service.settings.mapping import settings_entity, settings_out


class SettingsService:
    def __init__(self, session: AsyncSession):
        self.settings = SettingsRepo(session)

    async def get_settings(self) -> PlatformSettingsOut:
        row = await self.settings.get_or_create()
        await self.settings.session.commit()
        return settings_out(settings_entity(row.payload or {}, row.updated_at))
