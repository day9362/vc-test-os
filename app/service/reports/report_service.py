from collections import defaultdict
from math import sqrt
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.config import settings
from app.core.errors import AppError
from app.models.dto.report import (
    AmbientPointOut,
    BatchCompareOut,
    BatchStatOut,
    DeltaProfileOut,
    FailParetoOut,
    MachineYieldOut,
    RcHistogramOut,
    ReportDataOut,
    ReportExportIn,
    ReportExportOut,
    ReportNarrativeOut,
    ReportSummaryOut,
    ReportUsageOut,
)
from app.models.entity.user import UserEntity
from app.service.ai.usage import UsageService
from app.models.orm.report_figure import ReportFigureOrm
from app.models.orm.report_narrative import ReportNarrativeOrm
from app.models.orm.run import RunOrm
from app.repo.audit_repo import AuditRepo
from app.repo.run_repo import RunRepo
from app.service.reports.analysis_math import item_sort_key, usable
from app.service.reports.figures import batch_key
from app.service.reports.narrative import grounded_lines, polish_summary_lines, request_expert_summary, unify_words
from app.service.reports.pdf import PdfFigure, chart_bars, render_page_pdf, render_report_pdf
from app.service.reports.store import reports_dir, save_report_pdf
from app.service.runs.cluster_ingest import fleet_machine_ids
from app.service.runs.run_service import RunService

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
        runs = RunService(self.session)
        await runs._ensure_fleet()
        runs._schedule_ingest()
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
            ambient=_ambient_series({batch_id: grouped.get(batch_id, []) for batch_id in ids if grouped.get(batch_id)}),
            fail_pareto=_pareto(used),
            delta_profile=await _delta_profile(self.session, {batch_id: grouped.get(batch_id, []) for batch_id in ids if grouped.get(batch_id)}, len(active) == 1),
            compare=[BatchCompareOut(batch_id=item.batch_id, yield_rate=round(100 * item.passed / item.tested, 2), rc_mean=item.rc_mean) for item in active],
        )

    async def summary(self, batch_ids: list[str], user: UserEntity, mode: str = "single") -> ReportNarrativeOut:
        ids = [item.strip() for item in batch_ids if item and item.strip()]
        if not ids:
            raise AppError(400, "BAD_REQUEST", "batch_ids 不能为空")
        if mode not in {"single", "cross"}:
            raise AppError(400, "BAD_REQUEST", "mode 只能是 single 或 cross")
        from app.service.reports.analysis_service import AnalysisService

        analysis, rows = await AnalysisService(self.session).load(ids)
        if analysis.note and not analysis.overall.items:
            raise AppError(400, "BAD_REQUEST", analysis.note)
        payload = analysis.model_dump(mode="json")
        payload["batch_count"] = len(analysis.batches)
        started = now_ms()
        from app.service.settings.model import configured_model

        model_name = await configured_model(self.session)
        input_tokens = 0
        output_tokens = 0
        error: AppError | None = None
        lines: list[str] = []
        looked = ""
        try:
            text, evidence, input_tokens, output_tokens, model_name = await request_expert_summary(payload, model_name, mode, rows, self.session)
            lines = grounded_lines(text, evidence)
            looked = str(evidence.get("looked") or "")
        except AppError as exc:
            error = exc
        await UsageService(self.session).record(
            module="report",
            user=user.name,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=max(now_ms() - started, 1),
            ok=error is None,
            ref={"batch_ids": ids},
        )
        if error is None and lines:
            self.session.add(ReportNarrativeOrm(
                narrative_id=f"nar_{uuid4().hex[:8]}",
                batch_key=batch_key(ids),
                lines=lines,
                model=model_name,
                created_at=now_ms(),
            ))
        await self.session.commit()
        if error is not None:
            raise error
        return ReportNarrativeOut(lines=lines, model=model_name, usage=ReportUsageOut(input=input_tokens, output=output_tokens), looked=looked)

    async def saved_summary(self, batch_ids: list[str]) -> ReportNarrativeOut:
        ids = [item.strip() for item in batch_ids if item and item.strip()]
        row = await self._latest_narrative(ids)
        if row is None:
            return ReportNarrativeOut(lines=[], model="", usage=ReportUsageOut(input=0, output=0))
        return ReportNarrativeOut(lines=polish_summary_lines([unify_words(line) for line in list(row.lines or [])]), model=row.model, usage=ReportUsageOut(input=0, output=0))

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
        if body.blocks:
            pdf = render_page_pdf(body.blocks)
            included: list[str] = []
            lines = [block.text for block in body.blocks if block.kind in {"h1", "h2", "text"} and block.text]
        else:
            data = await self.data(",".join(ids))
            lines = polish_summary_lines([unify_words(line) for line in _clean_lines(body.summary_lines)])
            if not lines:
                saved = await self._latest_narrative(ids)
                lines = polish_summary_lines([unify_words(line) for line in _clean_lines(list(saved.lines or []) if saved is not None else [])])
            figures, included = await self._export_figures(ids, body.figure_ids)
            pdf = render_report_pdf(data, lines, figures)
        url = save_report_pdf(pdf)
        self.audit.record(
            user.user_id,
            "report.export",
            "",
            {"batch_ids": ids, "figure_ids": included, "summary": bool(lines), "format": fmt},
            {"url": url},
        )
        out = ReportExportOut(url=url)
        await self.session.commit()
        await self._store(idempotency_key, out)
        return out

    async def _latest_narrative(self, batch_ids: list[str]) -> ReportNarrativeOrm | None:
        key = batch_key(batch_ids)
        if not key:
            return None
        return await self.session.scalar(
            select(ReportNarrativeOrm).where(ReportNarrativeOrm.batch_key == key).order_by(ReportNarrativeOrm.created_at.desc()).limit(1)
        )

    async def _export_figures(self, batch_ids: list[str], figure_ids: list[str]) -> tuple[list[PdfFigure], list[str]]:
        key = batch_key(batch_ids)
        if not key:
            return [], []
        wanted = [item.strip() for item in figure_ids if item and item.strip()]
        query = select(ReportFigureOrm).where(ReportFigureOrm.batch_key == key, ReportFigureOrm.status == "done").order_by(ReportFigureOrm.created_at.desc())
        if wanted:
            query = query.where(ReportFigureOrm.figure_id.in_(wanted))
        rows = (await self.session.scalars(query)).all()
        figures: list[PdfFigure] = []
        included: list[str] = []
        for row in rows:
            image = _figure_png(row.png_name)
            results = []
            for pair in row.results or []:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    results.append((str(pair[0])[:40], str(pair[1])[:80]))
            figures.append(PdfFigure(
                title=(row.title or row.prompt or "补充分析")[:40],
                prompt=(row.prompt or "")[:200],
                results=results[:20],
                bars=[] if image else chart_bars(row.echarts_option),
                image=image,
            ))
            included.append(row.figure_id)
        return figures, included

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


def _clean_lines(lines: list[str]) -> list[str]:
    cleaned = []
    for line in lines:
        text = " ".join(str(line).split())
        if text:
            cleaned.append(text[:500])
        if len(cleaned) >= 30:
            break
    return cleaned


def _figure_png(name: str) -> bytes | None:
    if not name or "/" in name or "\\" in name:
        return None
    path = reports_dir() / name
    if not path.is_file():
        return None
    return path.read_bytes()


def _empty(batches: list[BatchStatOut]) -> ReportDataOut:
    return ReportDataOut(
        batches=batches,
        summary=ReportSummaryOut(tested=0, passed=0, failed=0, aborted=0, yield_rate=0, rc_mean=0, rc_sd=0, cpk_t01=0, usl_t01=USL_T01, machine_count=0),
        machine_yield=[],
        rc_histogram=RcHistogramOut(edges=[], counts={}),
        ambient=[],
        fail_pareto=[],
        delta_profile=DeltaProfileOut(items=[], mean={}, p95=None, limit=[]),
        compare=[],
    )


def _share_text(count: int, total: int) -> str:
    rate = 100 * count / total
    text = f"{rate:.1f}".rstrip("0").rstrip(".")
    return f"{text}%"


def _main_fail_text(fails: dict[str, int], tested: int) -> tuple[str, int]:
    if not fails or not tested:
        return "", 0
    ranked = sorted(fails.items(), key=lambda pair: (-pair[1], pair[0]))
    shown = [(name, count) for name, count in ranked if count * 100 > tested * 40]
    if not shown:
        shown = ranked[:1]
    text = "、".join(f"{name} {_share_text(count, tested)}" for name, count in shown)
    return text, ranked[0][1]


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
    top_fail, top_count = _main_fail_text(fails, tested)
    by_machine: dict[str, list[RunOrm]] = defaultdict(list)
    for row in rows:
        by_machine[row.machine_id].append(row)
    ranked = [(machine_id, items) for machine_id, items in by_machine.items() if items]
    worst_id, worst_n, worst_passed = "", 0, 0
    if len(ranked) > 1:
        machine_id, items = min(
            ranked,
            key=lambda pair: sum(1 for row in pair[1] if row.passed is True) / len(pair[1]),
        )
        worst_id = machine_id
        worst_n = len(items)
        worst_passed = sum(1 for row in items if row.passed is True)
    dts = [float(row.dt01) for row in rows if row.dt01 is not None]
    dt_sd = _sd(dts)
    cpk = None if not dts else round((USL_T01 - _mean(dts)) / (3 * dt_sd), 2) if dt_sd else 0
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
        top_fail=top_fail,
        top_fail_count=top_count,
        cpk_t01=cpk,
        worst_machine_id=worst_id,
        worst_machine_n=worst_n,
        worst_machine_passed=worst_passed,
    )


def _histogram(grouped: dict[str, list[RunOrm]]) -> RcHistogramOut:
    values = [value for rows in grouped.values() for row in rows if (value := _ambient(row)) is not None]
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
            value = _ambient(row)
            if value is None:
                continue
            index = int((value - lo) / width)
            if index < 0:
                index = 0
            if index >= BINS:
                index = BINS - 1
            bins[index] += 1
        counts[batch_id] = bins
    return RcHistogramOut(edges=edges, counts=counts)


def _ambient_series(grouped: dict[str, list[RunOrm]]) -> list[AmbientPointOut]:
    points: list[AmbientPointOut] = []
    for batch_id, rows in grouped.items():
        for row in rows:
            value = _ambient(row)
            t01 = _t01(row)
            if value is None and t01 is None:
                continue
            points.append(AmbientPointOut(
                batch_id=batch_id,
                serial=row.serial_number or row.run_id,
                ended_at=int(row.ended_at or 0),
                machine_id=row.machine_id or "",
                slot_index=int(row.slot_index or 0),
                value=None if value is None else round(value, 3),
                t01=None if t01 is None else round(t01, 3),
            ))
    points.sort(key=lambda item: (item.ended_at, item.serial))
    return points


def _t01(row: RunOrm) -> float | None:
    result = row.result if isinstance(row.result, dict) else {}
    deltas = result.get("deltas") or {}
    if isinstance(deltas, dict):
        value = deltas.get("Temp_T0-T1")
        if isinstance(value, (int, float)):
            return float(value)
    if isinstance(row.dt01, (int, float)):
        return float(row.dt01)
    return None


def _ambient(row: RunOrm) -> float | None:
    result = row.result if isinstance(row.result, dict) else {}
    deltas = result.get("deltas") or {}
    if isinstance(deltas, dict):
        for key in ("Temp_Ta", "Ta", "temp_ambient"):
            value = deltas.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    for item in result.get("temps") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("channel") or item.get("item") or "").lower()
        if name in {"ta", "t_a", "ambient"}:
            value = item.get("value")
            if isinstance(value, (int, float)):
                return float(value)
    return None


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
    return [FailParetoOut(item=item, count=count) for item, count in sorted(counts.items(), key=lambda pair: (-pair[1], item_sort_key(pair[0])))]


async def _delta_profile(session: AsyncSession, grouped: dict[str, list[RunOrm]], single: bool) -> DeltaProfileOut:
    from app.service.reports.analysis_service import AnalysisService

    rows = [row for batch in grouped.values() for row in batch]
    return _delta_profile_from(grouped, await AnalysisService(session)._limits(rows), single)


def _delta_profile_from(grouped: dict[str, list[RunOrm]], limits: dict, single: bool) -> DeltaProfileOut:
    from app.service.reports.analysis_service import _measured

    rows = [row for batch in grouped.values() for row in batch]
    needed = {(row.plan_id, int(row.plan_version or 0)) for row in rows if row.plan_id}
    catalog: dict[str, dict] = {}
    for key in needed:
        for measure, (name, _low, high) in (limits.get(key) or {}).items():
            if not str(measure).startswith("delta_"):
                continue
            slot = catalog.setdefault(str(measure), {"name": name, "highs": []})
            slot["name"] = name
            if isinstance(high, (int, float)) and not isinstance(high, bool):
                slot["highs"].append(float(high))
    measures = sorted(catalog, key=lambda measure: item_sort_key(catalog[measure]["name"]))
    items = [catalog[measure]["name"] for measure in measures]
    limit = [_agreed(catalog[measure]["highs"]) for measure in measures]
    mean = {batch_id: [_average(_readings(batch, measure, _measured)) for measure in measures] for batch_id, batch in grouped.items()}
    p95 = [_percentile(_readings(next(iter(grouped.values())), measure, _measured)) for measure in measures] if single and grouped else None
    return DeltaProfileOut(items=items, mean=mean, p95=p95, limit=limit)


def _readings(rows: list[RunOrm], measure: str, measured) -> list[float]:
    values = []
    for row in rows:
        raw = measured(row).get(measure)
        if raw is not None and usable(raw):
            values.append(float(raw))
    return values


def _agreed(values: list[float]) -> float | None:
    if not values or any(value != values[0] for value in values):
        return None
    return values[0]


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _percentile(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(0.95 * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def _sd(values: list[float]) -> float:
    if len(values) < 2:
        return 0
    avg = _mean(values)
    return sqrt(sum((value - avg) ** 2 for value in values) / len(values))


