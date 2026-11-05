import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.clock import now_ms
from app.core.database import SessionLocal
from app.service.production.sync import CatalogSync, publish_catalog
from app.service.realtime.watch import watch_changes
from app.service.runs.cluster_ingest import ingest_run_list, sync_samples
from app.service.settings.defaults import DEFAULT_JOBS, min_interval
from app.service.test_plan.cluster import ingest_cluster_plans
from app.tasks.job_runs import record
from app.tasks.sync import rollup_agg, scan_alarms, sync_calib, sync_cluster, sync_machine_details, sync_slots

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


async def _alarm_job() -> None:
    await _run(scan_alarms)


async def _watch_job() -> None:
    await _run(watch_changes)


async def _plans_job(session) -> None:
    await ingest_cluster_plans(session, refresh=True)


async def _runs_job(session) -> None:
    await ingest_run_list(session)


async def _batches_job() -> None:
    started = now_ms()
    failed = False
    snapshot, batches = None, []
    async with SessionLocal() as session:
        try:
            sync = CatalogSync(session)
            await sync.pull()
            snapshot, batches = await sync.refresh_stats(force=True)
            await session.commit()
        except Exception:
            await session.rollback()
            failed = True
            log.exception("scheduled job failed: batches")
    record("batches", now_ms() - started, failed)
    if snapshot is not None:
        await publish_catalog(snapshot, batches)


def _session_job(key: str, job):
    async def run() -> None:
        await _run(job, key)

    run.__name__ = key
    run.__qualname__ = key
    return run


_RUNNERS = {
    key: _session_job(key, job)
    for key, job in {
        "fleet": sync_cluster,
        "slots": sync_slots,
        "machine": sync_machine_details,
        "runs": _runs_job,
        "samples": sync_samples,
        "plans": _plans_job,
        "calib": sync_calib,
        "agg": rollup_agg,
    }.items()
}


def job_plan(payload: dict) -> list[tuple[str, int, bool]]:
    """设置页每一行对应的间隔和开关。缺行时用默认值。"""
    saved = {item.get("key"): item for item in payload.get("jobs") or []}
    plan = []
    for default in DEFAULT_JOBS:
        item = {**default, **(saved.get(default["key"]) or {})}
        seconds = max(int(item.get("interval_s") or default["interval_s"]), min_interval(default["key"]))
        plan.append((default["key"], seconds, bool(item.get("enabled", True))))
    return plan


def start_scheduler() -> None:
    if scheduler.running:
        return
    common = {"replace_existing": True, "max_instances": 1, "coalesce": True, "misfire_grace_time": 30}
    scheduler.add_job(_alarm_job, "interval", seconds=5, id="scan_alarms", **common)
    scheduler.add_job(_watch_job, "interval", seconds=1, id="realtime_watch", **common)
    scheduler.start()


def apply_job_intervals(payload: dict) -> None:
    if not scheduler.running:
        return
    for key, seconds, enabled in job_plan(payload):
        _replace(key, _batches_job if key == "batches" else _RUNNERS[key], seconds, enabled)


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
