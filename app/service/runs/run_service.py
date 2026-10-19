import asyncio
import csv
import io
import logging
from time import monotonic

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models.dto.run import RunDetailOut, RunGroundTruthOut, RunPageOut, RunSamplesOut
from app.repo.run_repo import RunRepo
from app.repo.settings_repo import SettingsRepo
from app.service.runs.cluster_ingest import fill_run_detail, fill_run_samples, fleet_machine_ids, ingest_run_list, refresh_fleet
from app.service.runs.mapping import run_detail_out, run_entity, run_out

log = logging.getLogger(__name__)
_last_ingest = 0.0
_INGEST_GAP_S = 60.0


class RunService:
    def __init__(self, session: AsyncSession):
        self.session = session
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
        await self._ensure_fleet()
        self._schedule_ingest()
        exclude_seed = bool(settings.cluster_base_url)
        fleet_ids = fleet_machine_ids() or None
        rows, next_cursor = await self.runs.page(
            machine_id, batch_id, passed_value, passed_is_null, status, q, start, end, cursor, limit, exclude_seed, fleet_ids
        )
        return RunPageOut(items=[run_out(run_entity(row)) for row in rows], next_cursor=next_cursor)

    async def get_run(self, run_id: str) -> RunDetailOut:
        await self._ensure_fleet()
        row = await self.runs.get(run_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 不存在")
        fleet = fleet_machine_ids()
        if fleet and row.machine_id not in fleet:
            raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 不在当前现场机台")
        row = await fill_run_detail(self.session, row)
        return run_detail_out(run_entity(row))

    async def get_samples(self, run_id: str, since: float | None) -> RunSamplesOut:
        await self._ensure_fleet()
        row = await self.runs.get(run_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 不存在")
        fleet = fleet_machine_ids()
        if fleet and row.machine_id not in fleet:
            raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 不在当前现场机台")
        row = await fill_run_detail(self.session, row)
        await fill_run_samples(self.session, run_id)
        samples = await self.runs.samples(run_id, since)
        raw_deltas = (row.result or {}).get("deltas") or {}
        deltas = {
            key: float(value)
            for key, value in (raw_deltas.items() if isinstance(raw_deltas, dict) else [])
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

    async def get_ground_truth(self, run_id: str) -> RunGroundTruthOut:
        payload = ((await SettingsRepo(self.session).get_or_create()).payload) or {}
        sim = payload.get("sim") or {}
        if payload.get("source") != "sim" or not sim.get("use_ground_truth"):
            raise AppError(404, "NOT_FOUND", "ground-truth 仅仿真且打开评估开关时可用")
        row = await self.runs.get(run_id)
        fleet = fleet_machine_ids()
        if row is not None and fleet and row.machine_id not in fleet:
            raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 不在当前现场机台")
        base = ((sim.get("base_url") or settings.cluster_base_url) or "").strip().rstrip("/")
        if not base:
            raise AppError(404, "NOT_FOUND", "ground-truth 仅仿真且打开评估开关时可用")
        timeout = max(float((payload.get("cluster") or {}).get("timeout_s") or settings.cluster_timeout_s), 30)
        try:
            response = await asyncio.to_thread(_get_ground_truth, f"{base}/runs/{run_id}/ground-truth", timeout)
        except httpx.TimeoutException as exc:
            raise AppError(504, "CLUSTER_TIMEOUT", "请求集群超时") from exc
        except httpx.HTTPError as exc:
            raise AppError(502, "CLUSTER_ERROR", "集群请求失败", {"upstream": str(exc)}) from exc
        if response.status_code == 404:
            raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 没有 ground-truth")
        if response.status_code >= 400:
            raise AppError(502, "CLUSTER_ERROR", "集群返回错误", {"upstream": response.text[:500]})
        try:
            body = response.json()
        except Exception as exc:
            raise AppError(502, "CLUSTER_ERROR", "集群返回无法解析") from exc
        if not isinstance(body, dict):
            raise AppError(502, "CLUSTER_ERROR", "集群返回无法解析")
        return RunGroundTruthOut.model_validate(body)

    async def _ensure_fleet(self) -> None:
        if settings.cluster_base_url and not fleet_machine_ids():
            await refresh_fleet()

    def _schedule_ingest(self) -> None:
        """集群 /runs 可能很慢，不挡列表；后台补齐本地库。"""
        global _last_ingest
        if not settings.cluster_base_url:
            return
        now = monotonic()
        if now - _last_ingest < _INGEST_GAP_S:
            return
        _last_ingest = now
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_ingest_in_background())

    async def export_csv(self, batch_id: str | None, start: int | None, end: int | None) -> str:
        await self._ensure_fleet()
        self._schedule_ingest()
        rows = await self.runs.list_for_export(batch_id, start, end, bool(settings.cluster_base_url), fleet_machine_ids() or None)
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


async def _ingest_in_background() -> None:
    try:
        async with SessionLocal() as session:
            await ingest_run_list(session)
    except Exception:
        log.warning("cluster run ingest skipped", exc_info=True)


def _get_ground_truth(url: str, timeout: float) -> httpx.Response:
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False, headers=headers) as client:
        return client.get(url)
