from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.settings import PlatformSettingsOut
from app.service.settings.settings_service import SettingsService

router = APIRouter(tags=["settings"])


@router.put("/settings", response_model=PlatformSettingsOut)
async def put_settings(
    body: PlatformSettingsOut,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> PlatformSettingsOut:
    return await SettingsService(session).save_settings(body)
