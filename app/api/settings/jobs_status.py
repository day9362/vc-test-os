from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.models.dto.settings import JobStatusOut
from app.service.settings.settings_service import SettingsService

router = APIRouter(tags=["settings"])


@router.get("/sync/jobs/status", response_model=JobStatusOut)
async def job_status(_: object = Depends(current_user)) -> JobStatusOut:
    return SettingsService.job_status()
