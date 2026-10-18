from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.machine import MachineActionOut
from app.models.entity.user import UserEntity
from app.service.machines.command_service import MachineCommandService

router = APIRouter(tags=["machines"])


@router.post("/machines/{machine_id}/power-on", response_model=MachineActionOut)
async def power_on(
    machine_id: str,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MachineActionOut:
    return await MachineCommandService(session, redis).power_on(machine_id, user, idempotency_key)
