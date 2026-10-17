from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.compensation import ChannelBiasOut
from app.service.compensation.compensation_service import CompensationService

router = APIRouter(tags=["compensation"])


@router.get("/machines/{machine_id}/channel-bias", response_model=ChannelBiasOut)
async def channel_bias(
    machine_id: str,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ChannelBiasOut:
    return await CompensationService(session).channel_bias(machine_id)
