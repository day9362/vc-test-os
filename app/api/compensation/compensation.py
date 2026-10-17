from fastapi import APIRouter, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.compensation import CompensationIn, CompensationOut, CompensationWriteOut
from app.models.entity.user import UserEntity
from app.service.compensation.compensation_service import CompensationService

router = APIRouter(tags=["compensation"])


@router.get("/machines/{machine_id}/compensation", response_model=CompensationOut)
async def get_compensation(
    machine_id: str,
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> CompensationOut:
    return await CompensationService(session).get_compensation(machine_id)


@router.put("/machines/{machine_id}/compensation", response_model=CompensationWriteOut)
async def put_compensation(
    machine_id: str,
    body: CompensationIn,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CompensationWriteOut:
    return await CompensationService(session, redis).put_compensation(machine_id, body, user, idempotency_key)
