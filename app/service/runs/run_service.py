from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.run import RunDetailOut, RunPageOut
from app.repo.run_repo import RunRepo
from app.service.runs.mapping import run_detail_out, run_entity, run_out


class RunService:
    def __init__(self, session: AsyncSession):
        self.runs = RunRepo(session)

    def _parse_passed(self, passed: str | None) -> tuple[bool | None, bool]:
        if passed is None or passed == "":
            return None, False
        if passed == "true":
            return True, False
        if passed == "false":
            return False, False
        if passed == "null":
            return None, True
        raise AppError(400, "BAD_REQUEST", "passed 只能是 true、false 或 null")

    async def list_runs(
        self,
        machine_id: str | None,
        batch_id: str | None,
        passed: str | None,
        status: str | None,
        q: str | None,
        start: int | None,
        end: int | None,
        cursor: str | None,
        limit: int,
    ) -> RunPageOut:
        if limit < 1 or limit > 500:
            raise AppError(400, "BAD_REQUEST", "limit 需要在 1 到 500 之间")
        if cursor and ":" not in cursor:
            raise AppError(400, "BAD_REQUEST", "cursor 格式不正确")
        passed_value, passed_is_null = self._parse_passed(passed)
        rows, next_cursor = await self.runs.page(
            machine_id, batch_id, passed_value, passed_is_null, status, q, start, end, cursor, limit
        )
        return RunPageOut(items=[run_out(run_entity(row)) for row in rows], next_cursor=next_cursor)

    async def get_run(self, run_id: str) -> RunDetailOut:
        row = await self.runs.get(run_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 不存在")
        return run_detail_out(run_entity(row))
