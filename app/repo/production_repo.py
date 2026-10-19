from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm.production import BatchRecordOrm, ProductModelOrm, ProductionOrm
from app.models.orm.run import RunOrm

STATS = ("running", "done", "stopped")


class ProductionRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def models(self) -> list[ProductModelOrm]:
        rows = await self.session.scalars(select(ProductModelOrm).order_by(ProductModelOrm.model))
        return list(rows.all())

    async def model(self, name: str) -> ProductModelOrm | None:
        return await self.session.get(ProductModelOrm, name)

    async def save_model(self, row: ProductModelOrm) -> None:
        await self.session.merge(row)

    async def batches(self) -> list[BatchRecordOrm]:
        rows = await self.session.scalars(select(BatchRecordOrm).order_by(BatchRecordOrm.batch_id))
        return list(rows.all())

    async def batch(self, batch_id: str) -> BatchRecordOrm | None:
        with self.session.no_autoflush:
            return await self.session.get(BatchRecordOrm, batch_id)

    async def save_batch(self, row: BatchRecordOrm) -> None:
        await self.session.merge(row)

    async def page_stats(
        self, *, state: str | None, model: str | None, q: str | None, cursor: str | None, limit: int,
    ) -> tuple[list[BatchRecordOrm], str | None]:
        stmt = select(BatchRecordOrm).where(BatchRecordOrm.state.in_(STATS))
        if state:
            stmt = stmt.where(BatchRecordOrm.state == state)
        if model:
            stmt = stmt.where(BatchRecordOrm.model == model)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(BatchRecordOrm.batch_id.ilike(like), BatchRecordOrm.model.ilike(like)))
        if cursor:
            mark_text, batch_id = cursor.split("|", 1)
            mark = int(mark_text)
            stmt = stmt.where(or_(
                BatchRecordOrm.started_at < mark,
                and_(BatchRecordOrm.started_at == mark, BatchRecordOrm.batch_id > batch_id),
            ))
        stmt = stmt.order_by(BatchRecordOrm.started_at.desc(), BatchRecordOrm.batch_id).limit(limit + 1)
        rows = list((await self.session.scalars(stmt)).all())
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = f"{last.started_at}|{last.batch_id}"
        return rows, next_cursor

    async def production(self) -> ProductionOrm | None:
        row = await self.session.get(ProductionOrm, 1)
        if row is None or not row.active:
            return None
        return row

    async def production_row(self) -> ProductionOrm:
        row = await self.session.get(ProductionOrm, 1)
        if row is None:
            row = ProductionOrm(id=1, active=False, batch_id="", queue_remaining=0, plan_id="", plan_version=0)
            self.session.add(row)
            await self.session.flush()
        return row

    async def runs_of(self, batch_id: str) -> list[RunOrm]:
        rows = await self.session.scalars(select(RunOrm).where(RunOrm.batch_id == batch_id))
        return list(rows.all())

    async def runs_grouped(self) -> dict[str, list[RunOrm]]:
        rows = await self.session.scalars(select(RunOrm).where(RunOrm.batch_id != ""))
        grouped: dict[str, list[RunOrm]] = {}
        for row in rows.all():
            grouped.setdefault(row.batch_id, []).append(row)
        return grouped
