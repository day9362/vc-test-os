from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.machine import SlotActionOut, SlotLoadIn
from app.models.entity.user import UserEntity
from app.service.machines.slot_service import SlotCommandService

router = APIRouter(tags=["machines"])


@router.post("/machines/{machine_id}/slots/{index}/load", response_model=SlotActionOut)
async def load(
    machine_id: str,
    index: int,
    body: SlotLoadIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SlotActionOut:
    return await SlotCommandService(session, redis).load(machine_id, index, body.serial_number, user, idempotency_key)


@router.post("/machines/{machine_id}/slots/{index}/start", response_model=SlotActionOut)
async def start(
    machine_id: str,
    index: int,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SlotActionOut:
    return await SlotCommandService(session, redis).start(machine_id, index, user, idempotency_key)


@router.post("/machines/{machine_id}/slots/{index}/abort", response_model=SlotActionOut)
async def abort(
    machine_id: str,
    index: int,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SlotActionOut:
    return await SlotCommandService(session, redis).abort(machine_id, index, user, idempotency_key)


@router.post("/machines/{machine_id}/slots/{index}/clear-error", response_model=SlotActionOut)
async def clear_error(
    machine_id: str,
    index: int,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SlotActionOut:
    return await SlotCommandService(session, redis).clear_error(machine_id, index, user, idempotency_key)
