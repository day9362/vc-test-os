import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.database import SessionLocal
from app.tasks.sync import rollup_agg, scan_alarms, sync_cluster

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def _run(job) -> None:
    async with SessionLocal() as session:
        try:
            await job(session)
            await session.commit()
        except Exception:
            await session.rollback()
            log.exception("scheduled job failed: %s", getattr(job, "__name__", job))


async def _sync_job() -> None:
    await _run(sync_cluster)


async def _alarm_job() -> None:
    await _run(scan_alarms)


async def _agg_job() -> None:
    await _run(rollup_agg)


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(_sync_job, "interval", seconds=2, id="sync_cluster", replace_existing=True)
    scheduler.add_job(_alarm_job, "interval", seconds=5, id="scan_alarms", replace_existing=True)
    scheduler.add_job(_agg_job, "interval", seconds=60, id="rollup_agg", replace_existing=True)
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
