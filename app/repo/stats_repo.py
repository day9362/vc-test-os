from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm.run import Agg5mOrm


class StatsRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def agg_between(self, start: int | None, end: int | None) -> list[Agg5mOrm]:
        stmt = select(Agg5mOrm).order_by(Agg5mOrm.bucket)
        if start is not None:
            stmt = stmt.where(Agg5mOrm.bucket >= start)
        if end is not None:
            stmt = stmt.where(Agg5mOrm.bucket < end)
        return list((await self.session.execute(stmt)).scalars().all())
