import logging
from collections import defaultdict
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.errors import AppError
from app.models.orm.production import BatchRecordOrm, ProductModelOrm, ProductionOrm
from app.models.orm.run import RunOrm
from app.repo.production_repo import ProductionRepo
from app.service.production.cluster import get_cluster, items
from app.service.realtime.publish import push_batch, push_production

log = logging.getLogger(__name__)

_ready = False
_batch_seen: dict[str, tuple] = {}
_production_seen: tuple | None = None
_fleet_queue_at = 0.0
_fleet_queue: int | None = None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def _sd(values: list[float]) -> float:
    if len(values) < 2:
        return 0
    mid = _mean(values)
    return (sum((value - mid) ** 2 for value in values) / len(values)) ** 0.5


def _top_fail(runs: list[RunOrm]) -> str:
    counts: dict[str, int] = {}
    for run in runs:
        for item in run.fail_items or []:
            counts[str(item)] = counts.get(str(item), 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)


def _pace_s(runs: list[RunOrm]) -> float:
    grouped: dict[str, list[int]] = defaultdict(list)
    for run in runs:
        if run.status == "RUNNING" or not run.ended_at:
            continue
        grouped[run.machine_id].append(run.ended_at)
    paces = []
    for times in grouped.values():
        times.sort()
        gaps = [(later - earlier) / 1000 for earlier, later in zip(times, times[1:]) if later > earlier]
        if gaps:
            paces.append(sum(gaps) / len(gaps))
    return sum(paces) / len(paces) if paces else 180


def _eta(remaining: int, runs: list[RunOrm], machines: int) -> int | None:
    if remaining <= 0:
        return None
    return int(remaining * _pace_s(runs) / max(machines, 1))


def apply_run_stats(row: BatchRecordOrm, runs: list[RunOrm], production: ProductionOrm | None) -> None:
    finished = [run for run in runs if run.status != "RUNNING"]
    row.tested = len(finished)
    row.passed = sum(1 for run in finished if run.passed is True)
    row.failed = sum(1 for run in finished if run.passed is False and run.status == "COMPLETED")
    row.aborted = sum(1 for run in finished if run.status in {"ABORTED", "FAULT"})
    machines = sorted({run.machine_id for run in runs if run.machine_id})
    if machines and not row.machine_ids:
        row.machine_ids = machines
    if runs and not row.plan_id:
        row.plan_id = runs[-1].plan_id
        row.plan_version = runs[-1].plan_version
    times = [run.ended_at for run in finished if run.ended_at]
    if times and not row.started_at:
        row.started_at = min(times)
    rcs = [float(run.rc) for run in finished if run.rc is not None]
    row.rc_mean = round(_mean(rcs), 3)
    row.rc_sd = round(_sd(rcs), 3)
    row.top_fail = _top_fail(finished)
    active = production is not None and production.active and production.batch_id == row.batch_id
    count = int(row.count or 0)
    tested = int(row.tested or 0)
    row.count = count
    row.tested = tested
    if not row.remaining_locked and count:
        row.remaining = max(count - tested, 0)
    still_open = int(row.remaining or 0) > 0 and not (count and tested >= count)
    if active and still_open:
        row.state = "running"
        row.ended_at = None
        row.plan_id = production.plan_id or row.plan_id
        row.plan_version = production.plan_version or row.plan_version
        count = len(row.machine_ids or machines) or 1
        row.eta_s = _eta(row.remaining, finished, count)
        return
    if active and row.tested:
        row.state = "done"
        row.ended_at = max(times) if times else row.ended_at
        row.eta_s = None
        production.active = False
        return
    if row.state == "stopped":
        row.eta_s = None
        return
    if row.tested:
        row.state = "done"
        row.ended_at = max(times) if times else row.ended_at
        row.eta_s = None


class CatalogSync:
    def __init__(self, session: AsyncSession):
        self.repo = ProductionRepo(session)

    async def pull(self) -> None:
        await self._models()
        await self._batches()
        await self._production()

    async def refresh_stats(self) -> tuple[dict | None, list[dict]]:
        grouped = await self.repo.runs_grouped()
        production = await self.repo.production_row()
        if production.active and await fleet_queue_remaining() == 0:
            _close_stuck_production(production, grouped.get(production.batch_id, []))
        for row in await self.repo.batches():
            apply_run_stats(row, grouped.get(row.batch_id, []), production)
        if production.active:
            batch = await self.repo.batch(production.batch_id)
            if batch is not None:
                production.queue_remaining = batch.remaining
        snapshot = _production_snapshot(production)
        changed = _changed_batches(await self.repo.batches())
        return snapshot, changed

    async def _models(self) -> None:
        try:
            payload = await get_cluster("/product-models")
        except AppError as exc:
            log.info("sync models skipped: %s", exc.message)
            return
        if payload is None:
            return
        for raw in items(payload, "models", "items"):
            name = raw.get("model")
            if not name:
                continue
            await self.repo.save_model(ProductModelOrm(
                model=str(name),
                resistance_mean=float(raw.get("resistance_mean") or 0),
                resistance_sd=float(raw.get("resistance_sd") or 0),
                power_w=float(raw.get("power_w") or 0),
            ))

    async def _batches(self) -> None:
        try:
            payload = await get_cluster("/products/batches")
        except AppError as exc:
            log.info("sync batches skipped: %s", exc.message)
            return
        if payload is None:
            return
        raw_rows = items(payload, "batches", "items")
        remaining = {}
        if any("remaining" not in raw for raw in raw_rows):
            remaining = await self._new_counts()
        for raw in raw_rows:
            batch_id = str(raw.get("batch_id") or "")
            if not batch_id:
                continue
            current = await self.repo.batch(batch_id)
            row = current or BatchRecordOrm(batch_id=batch_id, state="")
            row.model = str(raw.get("model") or row.model or "")
            row.count = int(raw.get("count") or row.count or 0)
            row.defect_ratio = float(raw.get("defect_ratio") or 0)
            row.batch_factor = float(raw.get("batch_factor") or 1)
            if "remaining" in raw and raw.get("remaining") is not None:
                row.remaining = int(raw.get("remaining") or 0)
                row.remaining_locked = True
            elif batch_id in remaining:
                row.remaining = remaining[batch_id]
                row.remaining_locked = True
            else:
                row.remaining_locked = False
                if row.count:
                    row.remaining = max(int(row.count or 0) - int(row.tested or 0), 0)
            await self.repo.save_batch(row)

    async def _new_counts(self) -> dict[str, int]:
        try:
            payload = await get_cluster("/products")
        except AppError as exc:
            log.info("sync products skipped: %s", exc.message)
            return {}
        if payload is None:
            return {}
        counts: dict[str, int] = {}
        for raw in items(payload, "products", "items"):
            if str(raw.get("state") or raw.get("status") or "") != "NEW":
                continue
            batch_id = str(raw.get("batch_id") or "")
            if batch_id:
                counts[batch_id] = counts.get(batch_id, 0) + 1
        return counts

    async def _production(self) -> None:
        payload = None
        reached = False
        for path in ("/fleet/production", "/production"):
            try:
                payload = await get_cluster(path)
            except AppError as exc:
                log.info("sync production %s skipped: %s", path, exc.message)
                return
            if payload is None:
                continue
            reached = True
            break
        if not reached:
            return
        row = await self.repo.production_row()
        if not isinstance(payload, dict) or not payload.get("batch_id"):
            row.active = False
            return
        row.active = True
        row.batch_id = str(payload.get("batch_id") or "")
        row.queue_remaining = int(payload.get("queue_remaining") or 0)
        row.plan_id = str(payload.get("plan_id") or "")
        row.plan_version = int(payload.get("plan_version") or 0)


def _close_stuck_production(production: ProductionOrm, runs: list[RunOrm]) -> None:
    """集群没有连续生产队列时，结束本地仍标着执行中的批次。"""
    production.active = False
    production.queue_remaining = 0
    stamp = now_ms()
    for run in runs:
        if run.status != "RUNNING":
            continue
        run.status = "ABORTED"
        run.ended_at = run.ended_at or stamp


async def fleet_queue_remaining() -> int | None:
    """机台队列合计。读不到集群时返回 None，避免把正在下发的任务误判成结束。"""
    global _fleet_queue_at, _fleet_queue
    if _fleet_queue is not None and monotonic() - _fleet_queue_at < 5:
        return _fleet_queue
    try:
        payload = await get_cluster("/fleet")
    except AppError as exc:
        log.info("sync fleet queue skipped: %s", exc.message)
        return None
    if payload is None:
        return None
    machines = items(payload, "machines", "items")
    if not machines and isinstance(payload, list):
        machines = [item for item in payload if isinstance(item, dict)]
    if not machines:
        return None
    queued = sum(int(item.get("queue_remaining") or 0) for item in machines)
    _fleet_queue = queued
    _fleet_queue_at = monotonic()
    return queued


def _production_snapshot(row: ProductionOrm) -> dict | None:
    if not row.active:
        return None
    return {
        "batch_id": row.batch_id,
        "queue_remaining": row.queue_remaining,
        "plan_id": row.plan_id,
        "plan_version": row.plan_version,
    }


def _signature(row: BatchRecordOrm) -> tuple:
    return (
        row.state, row.tested, row.passed, row.failed, row.aborted, row.remaining,
        row.rc_mean, row.rc_sd, row.top_fail, row.eta_s, row.ended_at, tuple(row.machine_ids or []),
    )


def _changed_batches(rows: list[BatchRecordOrm]) -> list[dict]:
    global _ready
    changed = []
    for row in rows:
        if row.state not in {"running", "done", "stopped"}:
            continue
        sign = _signature(row)
        if _ready and _batch_seen.get(row.batch_id) != sign:
            changed.append(_batch_body(row))
        _batch_seen[row.batch_id] = sign
    _ready = True
    return changed


def _batch_body(row: BatchRecordOrm) -> dict:
    from app.service.production.mapping import stat_out

    return stat_out(row).model_dump()


async def publish_catalog(snapshot: dict | None, batches: list[dict]) -> None:
    global _production_seen
    marker = None if snapshot is None else tuple(snapshot.get(key) for key in ("batch_id", "queue_remaining", "plan_id", "plan_version"))
    if marker != _production_seen:
        _production_seen = marker
        await push_production(snapshot)
    for batch in batches:
        await push_batch(batch)
