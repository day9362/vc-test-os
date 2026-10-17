from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.settings import TestConnectionIn, TestConnectionOut
from app.service.settings.settings_service import SettingsService

router = APIRouter(tags=["settings"])


@router.post("/settings/test-connection", response_model=TestConnectionOut)
async def test_connection(
    body: TestConnectionIn,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> TestConnectionOut:
    return await SettingsService(session).test_connection(body)
