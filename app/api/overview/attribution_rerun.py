from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.alarm import AttributionOut
from app.models.entity.user import UserEntity
from app.service.overview.alarm_service import AlarmService

router = APIRouter(tags=["overview"])


@router.post("/alarms/{alarm_id}/attribution", response_model=AttributionOut)
async def rerun_attribution(
    alarm_id: str,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AttributionOut:
    return await AlarmService(session).rerun_attribution(alarm_id, user)
