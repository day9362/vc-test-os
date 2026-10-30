import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.clock import now_ms
from app.core.database import SessionLocal
from app.service.production.sync import CatalogSync, publish_catalog
from app.service.realtime.watch import watch_changes
from app.tasks.job_runs import record
from app.tasks.sync import rollup_agg, scan_alarms, sync_cluster

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def _run(job, key: str | None = None) -> None:
    started = now_ms()
    failed = False
    async with SessionLocal() as session:
        try:
            await job(session)
            await session.commit()
        except Exception:
            await session.rollback()
            failed = True
            log.exception("scheduled job failed: %s", getattr(job, "__name__", job))
    if key:
        record(key, now_ms() - started, failed)


async def _sync_job() -> None:
    await _run(sync_cluster, "fleet")


async def _alarm_job() -> None:
    await _run(scan_alarms)


async def _agg_job() -> None:
    await _run(rollup_agg, "agg")


async def _watch_job() -> None:
    await _run(watch_changes)


async def _catalog_job() -> None:
    async with SessionLocal() as session:
        try:
            sync = CatalogSync(session)
            await sync.pull()
            snapshot, batches = await sync.refresh_stats()
            await session.commit()
        except Exception:
            await session.rollback()
            log.exception("scheduled job failed: catalog")
            return
    await publish_catalog(snapshot, batches)


def start_scheduler() -> None:
    if scheduler.running:
        return
    common = {"replace_existing": True, "max_instances": 1, "coalesce": True, "misfire_grace_time": 30}
    scheduler.add_job(_sync_job, "interval", seconds=2, id="sync_cluster", **common)
    scheduler.add_job(_alarm_job, "interval", seconds=5, id="scan_alarms", **common)
    scheduler.add_job(_agg_job, "interval", seconds=60, id="rollup_agg", **common)
    scheduler.add_job(_watch_job, "interval", seconds=1, id="realtime_watch", **common)
    scheduler.add_job(_catalog_job, "interval", seconds=30, id="sync_catalog", **common)
    scheduler.start()


def apply_job_intervals(payload: dict) -> None:
    if not scheduler.running:
        return
    jobs = {item.get("key"): item for item in payload.get("jobs") or []}
    fleet = jobs.get("fleet") or {}
    agg = jobs.get("agg") or {}
    _replace("sync_cluster", _sync_job, int(fleet.get("interval_s") or 2), bool(fleet.get("enabled", True)))
    _replace("rollup_agg", _agg_job, int(agg.get("interval_s") or 60), bool(agg.get("enabled", True)))


def _replace(job_id: str, func, seconds: int, enabled: bool) -> None:
    from apscheduler.jobstores.base import JobLookupError

    if not enabled:
        try:
            scheduler.remove_job(job_id)
        except JobLookupError:
            pass
        return
    scheduler.add_job(
        func,
        "interval",
        seconds=max(int(seconds), 1),
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
