import asyncio
import io
import logging
import zipfile
from time import monotonic

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models.dto.run import RunDetailOut, RunGroundTruthOut, RunPageOut, RunSamplesOut
from app.models.orm.production import BatchRecordOrm
from app.models.orm.test_plan import TestPlanOrm
from app.repo.run_repo import RunRepo
from app.repo.settings_repo import SettingsRepo
from app.service.runs.cluster_ingest import _apply_payload, _get, _result_t, _sample_rows, fill_run_detail, fill_run_samples, fleet_machine_ids, ingest_run_list, refresh_fleet
from app.service.settings.cluster_policy import request_timeout, sync_send
from app.service.runs.mapping import run_detail_out, run_entity, run_out
from app.service.runs.result_csv import build_result_export, choose_final_sample, export_date, points_from_body, raw_filename, render_raw, unique_names

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

    async def get_samples(self, run_id: str, since: float | None, limit: int | None = None) -> RunSamplesOut:
        await self._ensure_fleet()
        row = await self.runs.get(run_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 不存在")
        fleet = fleet_machine_ids()
        if fleet and row.machine_id not in fleet:
            raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 不在当前现场机台")
        row = await fill_run_detail(self.session, row)
        await fill_run_samples(self.session, run_id)
        samples = await self.runs.samples(run_id, since, limit)
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
        try:
            response = await asyncio.to_thread(_get_ground_truth, f"{base}/runs/{run_id}/ground-truth")
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

    async def export_csv(self, batch_id: str | None, start: int | None, end: int | None, group: str = "day") -> tuple[bytes, str, str]:
        if group not in {"day", "batch"}:
            raise AppError(400, "BAD_REQUEST", "group 只能是 day 或 batch")
        await self._ensure_fleet()
        self._schedule_ingest()
        rows = await self.runs.list_for_export(batch_id, start, end, bool(settings.cluster_base_url), fleet_machine_ids() or None)
        await self._settle_rows(rows)
        return build_result_export(rows, await self._batch_models(), await self._plan_durations(), group)

    async def export_products(self, run_ids: list[str]) -> tuple[bytes, str, str]:
        await self._ensure_fleet()
        fleet = fleet_machine_ids()
        ids = list(dict.fromkeys(run_ids))
        if not ids:
            raise AppError(400, "BAD_REQUEST", "先勾选要导出的产品")
        if len(ids) > 200:
            raise AppError(400, "BAD_REQUEST", "一次最多导出 200 个产品")
        picked = []
        for run_id in ids:
            row = await self.runs.get(run_id)
            if row is None or (fleet and row.machine_id not in fleet):
                raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 不存在")
            picked.append(row)
        latest = await self.runs.latest_by_serial([row.serial_number for row in picked if row.serial_number], fleet or None)
        chosen = []
        seen: set[str] = set()
        for row in picked:
            key = row.serial_number or row.run_id
            if key in seen:
                continue
            seen.add(key)
            chosen.append(latest.get(row.serial_number, row) if row.serial_number else row)
        await self._settle_rows(chosen)
        return build_result_export(chosen, await self._batch_models(), await self._plan_durations(), "products")

    async def export_raw(self, run_ids: list[str], batch_id: str | None) -> tuple[bytes, str, str]:
        await self._ensure_fleet()
        fleet = fleet_machine_ids()
        rows = []
        if run_ids:
            for run_id in dict.fromkeys(run_ids):
                row = await self.runs.get(run_id)
                if row is None or (fleet and row.machine_id not in fleet):
                    raise AppError(404, "NOT_FOUND", f"测试记录 {run_id} 不存在")
                rows.append(row)
        elif batch_id:
            rows = await self.runs.list_for_export(batch_id, None, None, bool(settings.cluster_base_url), fleet or None)
        if not rows:
            raise AppError(400, "BAD_REQUEST", "先选择要导出的测试记录")
        if len(rows) > 200:
            raise AppError(400, "BAD_REQUEST", "一次最多导出 200 片过程数据")
        files = []
        for row in rows:
            text = render_raw(await self._raw_points(row.run_id))
            files.append((raw_filename(row.batch_id, row.serial_number, row.ended_at, row.run_id), text))
        files = unique_names(files)
        if len(files) == 1:
            name, text = files[0]
            return text.encode("utf-8-sig"), "text/csv; charset=utf-8", name
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in files:
                archive.writestr(name, text.encode("utf-8-sig"))
        return buffer.getvalue(), "application/zip", f"rawdata_{export_date()}.zip"

    async def _settle_rows(self, rows: list) -> None:
        durations = await self._plan_durations()
        pending = []
        for row in rows:
            if getattr(row, "status", "") != "COMPLETED":
                continue
            duration = durations.get((str(row.plan_id or ""), int(row.plan_version or 0)))
            if not duration:
                continue
            current = _result_t(row.result if isinstance(row.result, dict) else None)
            if current is not None and current >= float(duration) - 1:
                continue
            pending.append((row, float(duration)))
        if not pending or not settings.cluster_base_url:
            return
        for start in range(0, len(pending), 6):
            chunk = pending[start : start + 6]
            loaded = await asyncio.gather(*(self._sample_rows(row.run_id) for row, _duration in chunk))
            for (row, duration), samples in zip(chunk, loaded):
                chosen = choose_final_sample(samples or [], duration)
                chosen_t = _result_t(chosen)
                if chosen is None or chosen_t is None or chosen_t < duration - 1:
                    continue
                _apply_payload(row, {"result": chosen, "status": row.status}, fill_result=True)
        await self.session.commit()

    async def _sample_rows(self, run_id: str) -> list[dict]:
        try:
            body = await asyncio.to_thread(_get, f"/runs/{run_id}/samples")
        except Exception:
            return []
        return _sample_rows(body)

    async def _raw_points(self, run_id: str) -> list[dict]:
        if settings.cluster_base_url:
            try:
                body = await asyncio.to_thread(_get, f"/runs/{run_id}/samples")
            except Exception:
                body = None
            points = points_from_body(body)
            if points:
                return points
        samples = await self.runs.samples(run_id, None, None)
        return [
            {"t_s": item.t_s, "temp_t0": item.t0, "temp_t1": item.t1, "temp_ambient": item.ta, "power_w": item.power_w}
            for item in samples
        ]

    async def _batch_models(self) -> dict[str, str]:
        found = await self.session.execute(select(BatchRecordOrm.batch_id, BatchRecordOrm.model))
        return {batch_id: model or "" for batch_id, model in found.all()}

    async def _plan_durations(self) -> dict[tuple[str, int], int]:
        found = await self.session.execute(select(TestPlanOrm.plan_id, TestPlanOrm.version, TestPlanOrm.duration_s))
        return {(plan_id, int(version)): int(duration) for plan_id, version, duration in found.all()}

    async def export_with_limits(self, plan_id: str, version: int | None, batch_id: str | None) -> dict:
        from app.repo.production_repo import ProductionRepo
        from app.service.runs.limit_csv import channel_value, columns_for, limit_map, render_csv
        from app.service.test_plan.plan_service import PlanService

        plan = await PlanService(self.session).get_plan(plan_id, version)
        limits = limit_map([item.model_dump() for item in plan.plan.limits])
        columns = columns_for(limits)
        await self._ensure_fleet()
        rows = await self.runs.list_for_export(batch_id, None, None, bool(settings.cluster_base_url), fleet_machine_ids() or None)
        await self._settle_rows(rows)
        counts = {item.batch_id: item.count for item in await ProductionRepo(self.session).batches()}
        data = []
        for row in rows:
            if row.status != "COMPLETED" or not row.keep_result:
                continue
            result = row.result if isinstance(row.result, dict) else {}
            item = {
                "batch_id": row.batch_id or "",
                "serial_number": row.serial_number or "",
                "batch_count": counts.get(row.batch_id or "", ""),
                "run_id": row.run_id,
                "machine_id": row.machine_id,
                "slot_index": row.slot_index,
                "plan_id": row.plan_id,
                "plan_version": row.plan_version,
                "passed": "" if row.passed is None else str(row.passed).lower(),
                "fail_items": "|".join(row.fail_items or []),
            }
            for column in columns:
                if column not in item:
                    item[column] = channel_value(result, column)
            data.append(item)
        return {
            "limits_plan_id": plan_id,
            "version": plan.plan.version,
            "data_rows": len(data),
            "csv": render_csv(columns, limits, data),
        }


async def _ingest_in_background() -> None:
    try:
        async with SessionLocal() as session:
            await ingest_run_list(session)
    except Exception:
        log.warning("cluster run ingest skipped", exc_info=True)


def _get_ground_truth(url: str) -> httpx.Response:
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    return sync_send("GET", url, timeout=request_timeout(), headers=headers)
