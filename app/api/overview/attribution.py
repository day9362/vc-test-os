from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.alarm import AttributionOut
from app.service.overview.alarm_service import AlarmService

router = APIRouter(tags=["overview"])


@router.get("/alarms/{alarm_id}/attribution", response_model=AttributionOut)
async def get_attribution(alarm_id: str, _: object = Depends(current_user), session: AsyncSession = Depends(get_session)) -> AttributionOut:
    return await AlarmService(session).attribution(alarm_id)
