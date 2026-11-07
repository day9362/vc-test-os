from __future__ import annotations

import asyncio
from time import monotonic

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.config import settings
from app.core.database import SessionLocal
from app.service.settings.cluster_policy import request_timeout, sync_send
from app.models.orm.run import RunOrm, RunSampleOrm

_cached_fleet: list[str] = []
_fleet_fail_at = 0.0
_FLEET_FAIL_TTL_S = 5.0
_metrics_task: asyncio.Task | None = None
_skip_metrics: set[str] = set()
_sample_miss_at: dict[str, float] = {}


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}


def _get(path: str) -> dict | list | None:
    base = settings.cluster_base_url.rstrip("/")
    if not base:
        return None
    res = sync_send("GET", f"{base}{path}", timeout=request_timeout(), headers=_headers())
    res.raise_for_status()
    return res.json()


def _get_fleet(path: str) -> dict | list | None:
    """机台列表过滤用：不超过设置的超时，也不超过 5 秒，避免 Agent 预览被集群拖死。"""
    base = settings.cluster_base_url.rstrip("/")
    if not base:
        return None
    res = sync_send("GET", f"{base}{path}", timeout=min(request_timeout(), 5.0), headers=_headers())
    res.raise_for_status()
    return res.json()


def fleet_machine_ids() -> list[str]:
    return list(_cached_fleet)


def _parse_fleet(body: object) -> list[str]:
    items = []
    if isinstance(body, dict):
        items = body.get("machines") or body.get("items") or []
    elif isinstance(body, list):
        items = body
    ids = []
    for item in items:
        if isinstance(item, dict) and item.get("machine_id"):
            ids.append(str(item["machine_id"]))
    return ids


async def refresh_fleet() -> list[str]:
    global _cached_fleet, _fleet_fail_at
    if not settings.cluster_base_url:
        return []
    if _cached_fleet:
        return list(_cached_fleet)
    if _fleet_fail_at and monotonic() - _fleet_fail_at < _FLEET_FAIL_TTL_S:
        return []
    try:
        body = await asyncio.to_thread(_get_fleet, "/fleet")
        ids = _parse_fleet(body)
        if ids:
            _cached_fleet = ids
            _fleet_fail_at = 0.0
    except Exception:
        _fleet_fail_at = monotonic()
    return list(_cached_fleet)


def _channel(temps: object, name: str) -> float | None:
    if not isinstance(temps, list):
        return None
    for item in temps:
        if isinstance(item, dict) and item.get("channel") == name and item.get("value") is not None:
            return float(item["value"])
    return None


def _deltas(result: dict) -> dict[str, float]:
    raw = result.get("deltas")
    out: dict[str, float] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, (int, float)):
                out[str(key)] = float(value)
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("item") or item.get("name") or item.get("channel") or "")
            value = item.get("value")
            if name and isinstance(value, (int, float)):
                out[name] = float(value)
    return out


def _named(deltas: dict[str, float], *names: str) -> float | None:
    lower = {key.lower(): value for key, value in deltas.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _rc_dt(payload: dict, result: dict) -> tuple[float | None, float | None]:
    deltas = _deltas(result)
    rc = _named(deltas, "Rc")
    dt = _named(deltas, "Temp_T0-T1", "T0-T1", "dt01")
    temps = result.get("temps")
    power = result.get("power_w")
    if dt is None:
        t0, t1 = _channel(temps, "T0"), _channel(temps, "T1")
        if t0 is not None and t1 is not None:
            dt = t0 - t1
    if rc is None and isinstance(power, (int, float)) and power:
        t1, ta = _channel(temps, "T1"), _channel(temps, "Ta")
        if t1 is not None and ta is not None:
            rc = (t1 - ta) / float(power)
    if rc is None and payload.get("rc") is not None:
        rc = float(payload["rc"])
    if dt is None and payload.get("dt01") is not None:
        dt = float(payload["dt01"])
    return rc, dt


def _apply_payload(row: RunOrm, payload: dict, *, fill_result: bool) -> None:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if fill_result and result:
        result = {**result, "deltas": _deltas(result) or result.get("deltas") or {}}
        row.result = result
    rc, dt = _rc_dt(payload, result or row.result or {})
    row.machine_id = str(payload.get("machine_id") or row.machine_id)
    row.slot_index = int(payload.get("slot_index") or row.slot_index or 0)
    row.serial_number = str(payload.get("serial_number") or row.serial_number or "")
    row.plan_id = str(payload.get("plan_id") or row.plan_id or "")
    row.plan_version = int(payload.get("plan_version") or row.plan_version or 0)
    row.status = str(payload.get("status") or row.status or "COMPLETED")
    row.passed = payload.get("passed") if "passed" in payload else row.passed
    row.fail_items = list(payload.get("fail_items") or row.fail_items or [])
    row.keep_result = True if payload.get("keep_result") is None else bool(payload["keep_result"])
    if rc is not None:
        row.rc = rc
    if dt is not None:
        row.dt01 = dt
    if payload.get("batch_id"):
        row.batch_id = str(payload["batch_id"])
    elif not row.batch_id:
        row.batch_id = ""
    ended = payload.get("ended_at")
    if isinstance(ended, (int, float)) and ended > 0:
        row.ended_at = int(ended)
    elif not row.ended_at:
        row.ended_at = now_ms()


def batch_of_serial(serial: str, batch_ids: list[str]) -> str:
    serial = (serial or "").strip()
    if not serial:
        return ""
    matches = [batch_id for batch_id in batch_ids if batch_id and (serial == batch_id or serial.startswith(batch_id + "-"))]
    return max(matches, key=len) if matches else ""


def _parse_batch_ids(body: object) -> list[str]:
    items = []
    if isinstance(body, dict):
        items = body.get("batches") or body.get("items") or []
    elif isinstance(body, list):
        items = body
    ids = []
    for item in items:
        if isinstance(item, dict) and item.get("batch_id"):
            ids.append(str(item["batch_id"]))
    return ids


async def refresh_batch_ids() -> list[str]:
    if not settings.cluster_base_url:
        return []
    try:
        body = await asyncio.to_thread(_get, "/products/batches")
        return _parse_batch_ids(body)
    except Exception:
        return []


async def ingest_run_list(session: AsyncSession) -> int:
    if not settings.cluster_base_url:
        return 0
    fleet = await refresh_fleet()
    if not fleet:
        return 0
    known_batches = await refresh_batch_ids()
    try:
        body = await asyncio.to_thread(_get, "/runs")
    except Exception:
        return 0
    items = []
    if isinstance(body, dict):
        items = body.get("runs") or body.get("items") or []
    elif isinstance(body, list):
        items = body
    allowed = set(fleet)
    count = 0
    for payload in items:
        if not isinstance(payload, dict) or not payload.get("run_id"):
            continue
        if str(payload.get("machine_id") or "") not in allowed:
            continue
        run_id = str(payload["run_id"])
        row = await session.get(RunOrm, run_id)
        if row is None:
            row = RunOrm(run_id=run_id, machine_id="", slot_index=0, serial_number="", plan_id="", plan_version=0, status="COMPLETED", passed=None, fail_items=[], keep_result=True, rc=None, dt01=None, batch_id="", ended_at=0, result={})
            session.add(row)
        _apply_payload(row, payload, fill_result=bool(payload.get("result")))
        if not row.batch_id:
            row.batch_id = batch_of_serial(row.serial_number, known_batches)
        count += 1
    await session.commit()
    _schedule_metrics_backfill()
    return count


async def _fetch_run_detail(run_id: str) -> tuple[str, dict | None]:
    try:
        payload = await asyncio.to_thread(_get, f"/runs/{run_id}")
    except Exception:
        return run_id, None
    return run_id, payload if isinstance(payload, dict) else None


def _schedule_metrics_backfill() -> None:
    global _metrics_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _metrics_task is not None and not _metrics_task.done():
        return
    _metrics_task = loop.create_task(_metrics_backfill_loop())


async def _metrics_backfill_loop() -> None:
    fleet = fleet_machine_ids()
    while fleet:
        async with SessionLocal() as session:
            stmt = select(RunOrm.run_id).where(
                or_(RunOrm.rc.is_(None), RunOrm.dt01.is_(None)),
                RunOrm.machine_id.in_(fleet),
            )
            if _skip_metrics:
                stmt = stmt.where(~RunOrm.run_id.in_(_skip_metrics))
            ids = list((await session.execute(stmt.limit(6))).scalars().all())
            if not ids:
                return
            sem = asyncio.Semaphore(3)

            async def one(run_id: str) -> tuple[str, dict | None]:
                async with sem:
                    return await _fetch_run_detail(run_id)

            pairs = await asyncio.gather(*(one(run_id) for run_id in ids))
            for run_id, payload in pairs:
                if not payload:
                    _skip_metrics.add(run_id)
                    continue
                row = await session.get(RunOrm, run_id)
                if row is None:
                    continue
                _apply_payload(row, payload, fill_result=True)
                if row.rc is None and row.dt01 is None:
                    _skip_metrics.add(run_id)
            await session.commit()
        await asyncio.sleep(0.2)
        fleet = fleet_machine_ids()


async def fill_run_detail(session: AsyncSession, row: RunOrm) -> RunOrm:
    if not settings.cluster_base_url:
        return row
    if row.result and row.rc is not None and row.dt01 is not None:
        return row
    try:
        payload = await asyncio.to_thread(_get, f"/runs/{row.run_id}")
    except Exception:
        return row
    if isinstance(payload, dict):
        _apply_payload(row, payload, fill_result=True)
    return row


def _sample_points(body: object) -> list[dict]:
    items = []
    if isinstance(body, dict):
        items = body.get("samples") or body.get("points") or []
    elif isinstance(body, list):
        items = body
    points = []
    for item in items:
        if not isinstance(item, dict):
            continue
        temps = item.get("temps")
        points.append({
            "t_s": float(item.get("t_s") or 0),
            "t0": _channel(temps, "T0") or 0,
            "t1": _channel(temps, "T1") or 0,
            "ta": _channel(temps, "Ta") or 0,
            "power_w": float(item.get("power_w") or 0),
        })
    return points


async def sync_samples(session: AsyncSession) -> None:
    """按过程曲线的间隔拉取。正在测试的记录按已有时间增量追加，缺曲线的已结束记录补一份。"""
    if not settings.cluster_base_url:
        return
    running = list((await session.execute(select(RunOrm).where(RunOrm.status == "RUNNING"))).scalars().all())
    seen = {row.run_id for row in running}
    pending = []
    for row in running:
        since = float((await session.execute(select(func.max(RunSampleOrm.t_s)).where(RunSampleOrm.run_id == row.run_id))).scalar() or 0)
        pending.append((row.run_id, since, True))
    missing = list((await session.execute(
        select(RunOrm)
        .where(RunOrm.status.in_(("COMPLETED", "ABORTED", "FAULT")))
        .where(~RunOrm.run_id.in_(select(RunSampleOrm.run_id)))
        .order_by(RunOrm.ended_at.desc())
        .limit(20)
    )).scalars().all())
    now = monotonic()
    picked = 0
    for row in missing:
        if row.run_id in seen or now - _sample_miss_at.get(row.run_id, 0) < 60:
            continue
        pending.append((row.run_id, 0.0, False))
        picked += 1
        if picked == 4:
            break
    fetched = await asyncio.gather(*(_fetch_sample_body(run_id, since, incremental) for run_id, since, incremental in pending))
    for run_id, since, incremental, points in fetched:
        if points is None:
            continue
        if not incremental:
            if not points:
                _sample_miss_at[run_id] = monotonic()
                continue
            existing = (await session.execute(select(RunSampleOrm.id).where(RunSampleOrm.run_id == run_id).limit(1))).first()
            if existing:
                continue
            await session.execute(delete(RunSampleOrm).where(RunSampleOrm.run_id == run_id))
            since = -1
        for point in points:
            if point["t_s"] <= since:
                continue
            session.add(RunSampleOrm(run_id=run_id, t_s=point["t_s"], t0=point["t0"], t1=point["t1"], ta=point["ta"], power_w=point["power_w"]))


async def _fetch_sample_body(run_id: str, since: float, incremental: bool):
    path = f"/runs/{run_id}/samples?since={since}" if incremental else f"/runs/{run_id}/samples"
    try:
        body = await asyncio.to_thread(_get, path)
    except Exception:
        return run_id, since, incremental, None
    return run_id, since, incremental, _sample_points(body)


async def fill_run_samples(session: AsyncSession, run_id: str) -> None:
    if not settings.cluster_base_url:
        return
    existing = (await session.execute(select(RunSampleOrm.id).where(RunSampleOrm.run_id == run_id).limit(1))).first()
    if existing:
        return
    try:
        body = await asyncio.to_thread(_get, f"/runs/{run_id}/samples")
    except Exception:
        return
    points = _sample_points(body)
    if not points:
        return
    await session.execute(delete(RunSampleOrm).where(RunSampleOrm.run_id == run_id))
    for point in points:
        session.add(RunSampleOrm(run_id=run_id, t_s=point["t_s"], t0=point["t0"], t1=point["t1"], ta=point["ta"], power_w=point["power_w"]))
