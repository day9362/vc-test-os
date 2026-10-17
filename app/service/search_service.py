from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.search import SearchHitOut, SearchOut
from app.repo.machine_repo import MachineRepo
from app.repo.run_repo import RunRepo


class SearchService:
    def __init__(self, session: AsyncSession):
        self.machines = MachineRepo(session)
        self.runs = RunRepo(session)

    async def search(self, q: str, limit: int) -> SearchOut:
        if limit < 1 or limit > 50:
            raise AppError(400, "BAD_REQUEST", "limit 需要在 1 到 50 之间")
        query = (q or "").strip()
        if not query:
            return SearchOut(machines=[], batches=[], plans=[], runs=[])
        machines = await self.machines.search(query, limit)
        batches = await self.runs.search_batches(query, limit)
        plans = await self.runs.search_plans(query, limit)
        runs = await self.runs.search_runs(query, limit)
        return SearchOut(
            machines=[SearchHitOut(id=row.machine_id, text=f"{row.machine_id} · {row.serial}" if row.serial else row.machine_id) for row in machines],
            batches=[SearchHitOut(id=batch_id, text=batch_id) for batch_id in batches],
            plans=[SearchHitOut(id=plan_id, text=plan_id) for plan_id in plans],
            runs=[SearchHitOut(id=row.run_id, text=f"{row.run_id} · {row.serial_number}" if row.serial_number else row.run_id) for row in runs],
        )
