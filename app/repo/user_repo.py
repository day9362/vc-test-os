from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity.user import UserEntity
from app.models.orm.user import UserOrm


def _to_entity(row: UserOrm) -> UserEntity:
    return UserEntity(row.user_id, row.username, row.name, row.role, row.password_hash)


class UserRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def by_username(self, username: str) -> UserEntity | None:
        row = (await self.session.execute(select(UserOrm).where(UserOrm.username == username))).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def by_id(self, user_id: str) -> UserEntity | None:
        row = await self.session.get(UserOrm, user_id)
        return _to_entity(row) if row else None

    async def add(self, user: UserEntity) -> None:
        self.session.add(UserOrm(
            user_id=user.user_id,
            username=user.username,
            name=user.name,
            role=user.role,
            password_hash=user.password_hash,
        ))
