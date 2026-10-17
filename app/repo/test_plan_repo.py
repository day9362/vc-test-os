from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm.test_plan import TestPlanOrm


class TestPlanRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def all(self) -> list[TestPlanOrm]:
        return list((await self.session.execute(select(TestPlanOrm).order_by(TestPlanOrm.updated_at.desc()))).scalars().all())

    async def of(self, plan_id: str) -> list[TestPlanOrm]:
        return list((await self.session.execute(select(TestPlanOrm).where(TestPlanOrm.plan_id == plan_id))).scalars().all())

    async def one(self, plan_id: str, version: int) -> TestPlanOrm | None:
        return (await self.session.execute(
            select(TestPlanOrm).where(TestPlanOrm.plan_id == plan_id, TestPlanOrm.version == version)
        )).scalar_one_or_none()

    def add(self, row: TestPlanOrm) -> None:
        self.session.add(row)

    async def delete(self, row: TestPlanOrm) -> None:
        await self.session.delete(row)
