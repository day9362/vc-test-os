from collections import defaultdict
from math import sqrt

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.models.dto.report import (
    BatchCompareOut,
    BatchStatOut,
    DeltaProfileOut,
    FailParetoOut,
    MachineYieldOut,
    RcHistogramOut,
    ReportDataOut,
    ReportExportIn,
    ReportExportOut,
    ReportSummaryOut,
)
from app.models.entity.user import UserEntity
from app.models.orm.run import RunOrm
from app.repo.audit_repo import AuditRepo
from app.repo.run_repo import RunRepo
from app.service.reports.pdf import render_report_pdf
from app.service.reports.store import save_report_pdf
from app.service.runs.cluster_ingest import fleet_machine_ids, ingest_run_list, refresh_fleet

USL_T01 = 2.8
BINS = 28


class ReportService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.session = session
        self.runs = RunRepo(session)
        self.audit = AuditRepo(session)
        self.redis = redis

    async def data(self, batch_ids: str) -> ReportDataOut:
        ids = [item.strip() for item in (batch_ids or "").split(",") if item.strip()]
        if not ids:
            raise AppError(400, "BAD_REQUEST", "batch_ids 不能为空")
        if settings.cluster_base_url:
            await refresh_fleet()
            await ingest_run_list(self.session)
            await self.session.commit()
        rows = await self.runs.list_by_batches(ids, fleet_machine_ids() or None)
        grouped: dict[str, list[RunOrm]] = {batch_id: [] for batch_id in ids}
        for row in rows:
            grouped.setdefault(row.batch_id, []).append(row)
        batches = [_batch_stat(batch_id, grouped.get(batch_id, [])) for batch_id in ids]
        active = [item for item in batches if item.tested > 0]
        used = [row for batch_id in ids for row in grouped.get(batch_id, [])]
        if not active:
            return _empty(batches)
        rcs = [float(row.rc) for row in used if row.rc is not None]
        dts = [float(row.dt01) for row in used if row.dt01 is not None]
        tested = sum(item.tested for item in active)
        passed = sum(item.passed for item in active)
        failed = sum(item.failed for item in active)
        aborted = sum(item.aborted for item in active)
        rc_mean = _mean(rcs)
        rc_sd = _sd(rcs)
        dt_mean = _mean(dts)
        dt_sd = _sd(dts)
        cpk = (USL_T01 - dt_mean) / (3 * dt_sd) if dt_sd else 0
        machines: dict[str, list[RunOrm]] = defaultdict(list)
        for row in used:
            machines[row.machine_id].append(row)
        return ReportDataOut(
            batches=batches,
            summary=ReportSummaryOut(
                tested=tested,
                passed=passed,
                failed=failed,
                aborted=aborted,
                yield_rate=round(100 * passed / tested, 2) if tested else 0,
                rc_mean=round(rc_mean, 3),
                rc_sd=round(rc_sd, 3),
                cpk_t01=round(cpk, 2),
                usl_t01=USL_T01,
                machine_count=len(machines),
            ),
            machine_yield=[
                MachineYieldOut(machine_id=machine_id, n=len(items), passed=sum(1 for row in items if row.passed is True))
                for machine_id, items in sorted(machines.items())
            ],
            rc_histogram=_histogram({batch_id: grouped.get(batch_id, []) for batch_id in ids if grouped.get(batch_id)}),
            fail_pareto=_pareto(used),
            delta_profile=_deltas({batch_id: grouped.get(batch_id, []) for batch_id in ids if grouped.get(batch_id)}, len(active) == 1),
            compare=[BatchCompareOut(batch_id=item.batch_id, yield_rate=round(100 * item.passed / item.tested, 2), rc_mean=item.rc_mean) for item in active],
        )

    async def export(self, body: ReportExportIn, user: UserEntity, idempotency_key: str | None) -> ReportExportOut:
        cached = await self._cached(idempotency_key)
        if cached:
            return ReportExportOut.model_validate(cached)
        ids = [item.strip() for item in body.batch_ids if item and item.strip()]
        if not ids:
            raise AppError(400, "BAD_REQUEST", "batch_ids 不能为空")
        fmt = (body.format or "pdf").strip().lower()
        if fmt != "pdf":
            raise AppError(422, "VALIDATION_ERROR", "目前仅支持 format=pdf")
        data = await self.data(",".join(ids))
        skipped = [item for item in body.figure_ids if item]
        figure_note = None
        if skipped:
            figure_note = f"图表尚未接入导出（8.3 未实现），已忽略 figure_ids: {', '.join(skipped)}"
        pdf = render_report_pdf(data, figure_note)
        url = save_report_pdf(pdf)
        self.audit.record(user.user_id, "report.export", "", {"batch_ids": ids, "figure_ids": skipped, "format": fmt}, {"url": url})
        out = ReportExportOut(url=url)
        await self.session.commit()
        await self._store(idempotency_key, out)
        return out

    async def _cached(self, key: str | None):
        if not key or self.redis is None:
            return None
        raw = await self.redis.get(f"idem:{key}")
        if not raw:
            return None
        import json
        return json.loads(raw)

    async def _store(self, key: str | None, body: ReportExportOut) -> None:
        if not key or self.redis is None:
            return
        import json
        await self.redis.set(f"idem:{key}", json.dumps(body.model_dump()), ex=600)


def _empty(batches: list[BatchStatOut]) -> ReportDataOut:
    return ReportDataOut(
        batches=batches,
        summary=ReportSummaryOut(tested=0, passed=0, failed=0, aborted=0, yield_rate=0, rc_mean=0, rc_sd=0, cpk_t01=0, usl_t01=USL_T01, machine_count=0),
        machine_yield=[],
        rc_histogram=RcHistogramOut(edges=[], counts={}),
        fail_pareto=[],
        delta_profile=DeltaProfileOut(items=[], mean={}, p95=None, limit=[]),
        compare=[],
    )


def _batch_stat(batch_id: str, rows: list[RunOrm]) -> BatchStatOut:
    tested = len(rows)
    passed = sum(1 for row in rows if row.passed is True)
    failed = sum(1 for row in rows if row.passed is False and row.status == "COMPLETED")
    aborted = sum(1 for row in rows if row.status in {"ABORTED", "FAULT"})
    rcs = [float(row.rc) for row in rows if row.rc is not None]
    fails: dict[str, int] = defaultdict(int)
    for row in rows:
        for item in row.fail_items or []:
            fails[str(item)] += 1
    machines = sorted({row.machine_id for row in rows})
    times = [row.ended_at for row in rows if row.ended_at]
    running = any(row.status == "RUNNING" for row in rows)
    first = rows[0] if rows else None
    return BatchStatOut(
        batch_id=batch_id,
        model="",
        count=tested,
        tested=tested,
        passed=passed,
        failed=failed,
        aborted=aborted,
        plan_id=first.plan_id if first else "",
        plan_version=first.plan_version if first else 0,
        machine_ids=machines,
        started_at=min(times) if times else 0,
        ended_at=None if running or not times else max(times),
        state="running" if running else "done",
        rc_mean=round(_mean(rcs), 3),
        rc_sd=round(_sd(rcs), 3),
        top_fail=max(fails, key=fails.get) if fails else "",
    )


def _histogram(grouped: dict[str, list[RunOrm]]) -> RcHistogramOut:
    values = [float(row.rc) for rows in grouped.values() for row in rows if row.rc is not None]
    if not values:
        return RcHistogramOut(edges=[], counts={})
    lo = min(values) - 0.05
    hi = max(values) + 0.05
    if hi <= lo:
        hi = lo + 0.1
    width = (hi - lo) / BINS
    edges = [round(lo + width * index, 4) for index in range(BINS + 1)]
    counts: dict[str, list[int]] = {}
    for batch_id, rows in grouped.items():
        bins = [0] * BINS
        for row in rows:
            if row.rc is None:
                continue
            index = int((float(row.rc) - lo) / width)
            if index < 0:
                index = 0
            if index >= BINS:
                index = BINS - 1
            bins[index] += 1
        counts[batch_id] = bins
    return RcHistogramOut(edges=edges, counts=counts)


def _pareto(rows: list[RunOrm]) -> list[FailParetoOut]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.passed is not False:
            continue
        items = row.fail_items or []
        if not items:
            counts["unknown"] += 1
            continue
        for item in items:
            counts[str(item)] += 1
    return [FailParetoOut(item=item, count=count) for item, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))]


def _deltas(grouped: dict[str, list[RunOrm]], single: bool) -> DeltaProfileOut:
    keys: set[str] = set()
    for rows in grouped.values():
        for row in rows:
            for key in (row.result or {}).get("deltas") or {}:
                if key != "Rc":
                    keys.add(str(key))
    items = sorted(keys)
    mean: dict[str, list[float]] = {}
    for batch_id, rows in grouped.items():
        mean[batch_id] = [_mean(_delta_values(rows, key)) for key in items]
    p95 = [_p95(_delta_values(next(iter(grouped.values())), key)) for key in items] if single and grouped else None
    limit = [USL_T01 if key == "Temp_T0-T1" else None for key in items]
    return DeltaProfileOut(items=items, mean=mean, p95=p95, limit=limit)


def _delta_values(rows: list[RunOrm], key: str) -> list[float]:
    values = []
    for row in rows:
        raw = ((row.result or {}).get("deltas") or {}).get(key)
        if isinstance(raw, (int, float)):
            values.append(float(raw))
    return values


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def _sd(values: list[float]) -> float:
    if len(values) < 2:
        return 0
    avg = _mean(values)
    return sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _p95(values: list[float]) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(0.95 * (len(ordered) - 1)))))
    return round(ordered[index], 3)
