from redis.asyncio import Redis

from app.core.errors import AppError
from app.core.security import decode_token, issue_token, verify_password
from app.models.entity.user import UserEntity
from app.repo.user_repo import UserRepo


class AuthService:
    def __init__(self, users: UserRepo, redis: Redis):
        self.users = users
        self.redis = redis

    async def login(self, tenant_id: str, username: str, password: str) -> str:
        tenant = await self.users.tenant(tenant_id)
        user = await self.users.by_username(username, tenant_id) if tenant is not None else None
        if tenant is None or user is None or not verify_password(password, user.password_hash):
            raise AppError(401, "UNAUTHORIZED", "租户、用户名或密码错误")
        token, jti, exp = issue_token(user.user_id, user.name, user.role, tenant.tenant_id, tenant.name)
        ttl = max(1, exp - _now())
        await self.redis.set(f"auth:session:{jti}", user.user_id, ex=ttl)
        await self.redis.set(f"auth:user:{user.user_id}", jti, ex=ttl)
        return token

    async def list_tenants(self) -> list[tuple[str, str]]:
        return [(row.tenant_id, row.name) for row in await self.users.tenants()]

    async def logout(self, token: str) -> None:
        payload = decode_token(token)
        jti = payload["jti"]
        user_id = payload["sub"]
        await self.redis.delete(f"auth:session:{jti}")
        current = await self.redis.get(f"auth:user:{user_id}")
        if current == jti:
            await self.redis.delete(f"auth:user:{user_id}")

    async def current_user(self, token: str) -> UserEntity:
        payload = decode_token(token)
        active = await self.redis.get(f"auth:session:{payload['jti']}")
        if active != payload["sub"]:
            raise AppError(401, "UNAUTHORIZED", "登录已失效")
        user = await self.users.by_id(payload["sub"])
        if user is None:
            raise AppError(401, "UNAUTHORIZED", "登录已失效")
        tenant = await self.users.tenant(user.tenant_id)
        user.tenant_name = tenant.name if tenant is not None else user.tenant_id
        return user


def _now() -> int:
    from time import time
    return int(time())
