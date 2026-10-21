from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.redis import get_redis
from app.models.dto.auth import TenantOut
from app.repo.user_repo import UserRepo
from app.service.auth_service import AuthService
from redis.asyncio import Redis

router = APIRouter(tags=["auth"])


@router.get("/auth/tenants", response_model=list[TenantOut])
async def list_tenants(session: AsyncSession = Depends(get_session), redis: Redis = Depends(get_redis)) -> list[TenantOut]:
    rows = await AuthService(UserRepo(session), redis).list_tenants()
    return [TenantOut(tenant_id=tenant_id, name=name) for tenant_id, name in rows]
