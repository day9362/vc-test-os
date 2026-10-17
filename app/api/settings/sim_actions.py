from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.settings import ClockIn, FaultInjectIn, ScenarioApplyIn, SimActionOut
from app.models.entity.user import UserEntity
from app.service.settings.settings_service import SettingsService

router = APIRouter(tags=["settings"])


@router.put("/sim/clock", response_model=SimActionOut)
async def set_clock(
    body: ClockIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SimActionOut:
    return await SettingsService(session, redis).set_clock(body, user, idempotency_key)


@router.post("/sim/scenarios/{name}/apply", response_model=SimActionOut)
async def apply_scenario(
    name: str,
    body: ScenarioApplyIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SimActionOut:
    return await SettingsService(session, redis).apply_scenario(name, body, user, idempotency_key)


@router.post("/sim/faults", response_model=SimActionOut)
async def inject_fault(
    body: FaultInjectIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SimActionOut:
    return await SettingsService(session, redis).inject_fault(body, user, idempotency_key)
