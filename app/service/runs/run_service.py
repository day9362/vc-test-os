import csv
import io

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.run import RunDetailOut, RunPageOut, RunSamplesOut
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

    async def get_samples(self, run_id: str, since: float | None) -> RunSamplesOut:
        row = await self.runs.get(run_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 不存在")
        samples = await self.runs.samples(run_id, since)
        deltas = {
            key: float(value)
            for key, value in (row.result or {}).get("deltas", {}).items()
            if isinstance(value, (int, float))
        }
        duration = (row.result or {}).get("duration_s")
        if duration is None and samples:
            duration = int(samples[-1].t_s)
        return RunSamplesOut(
            run_id=row.run_id,
            plan_id=row.plan_id,
            plan_version=row.plan_version,
            duration_s=duration,
            points=[
                {"t_s": item.t_s, "T0": item.t0, "T1": item.t1, "Ta": item.ta, "power_w": item.power_w}
                for item in samples
            ],
            deltas=deltas,
        )

    async def export_csv(self, batch_id: str | None, start: int | None, end: int | None) -> str:
        rows = await self.runs.list_for_export(batch_id, start, end)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "run_id", "machine_id", "slot_index", "serial_number", "plan_id", "plan_version",
            "status", "passed", "fail_items", "keep_result", "rc", "dt01", "batch_id", "ended_at",
        ])
        for row in rows:
            writer.writerow([
                row.run_id,
                row.machine_id,
                row.slot_index,
                row.serial_number or "",
                row.plan_id,
                row.plan_version,
                row.status,
                "" if row.passed is None else str(row.passed).lower(),
                "|".join(row.fail_items or []),
                str(row.keep_result).lower(),
                "" if row.rc is None else row.rc,
                "" if row.dt01 is None else row.dt01,
                row.batch_id or "",
                row.ended_at,
            ])
        return buffer.getvalue()
