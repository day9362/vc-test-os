import logging
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.config import settings
from app.models.orm.alarm import AlarmOrm
from app.models.orm.machine import MachineOrm, SlotOrm
from app.models.orm.run import Agg5mOrm, RunOrm
from app.service.overview.attribution import build_attribution
from app.service.overview.hub import hub
from app.service.overview.machine_service import MachineService
from app.service.overview.mapping import alarm_entity, alarm_out

log = logging.getLogger(__name__)


async def sync_cluster(session: AsyncSession) -> None:
    """定时任务：按设置里的地址拉取机群和槽位，失败时保留库里的上一份快照。"""
    base = settings.cluster_base_url.rstrip("/")
    if not base:
        await _touch(session)
        return
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    try:
        async with httpx.AsyncClient(timeout=settings.cluster_timeout_s) as client:
            fleet = await client.get(f"{base}/fleet", headers=headers)
            fleet.raise_for_status()
            payload = fleet.json()
    except Exception as exc:
        log.warning("cluster fleet sync failed: %s", exc)
        return
    machines = payload if isinstance(payload, list) else payload.get("machines") or payload.get("items") or []
    changed = []
    for item in machines:
        if not isinstance(item, dict) or "machine_id" not in item:
            continue
        row = await _upsert_machine(session, item)
        changed.append(row.machine_id)
        if row.comm_status == "DISCONNECTED":
            continue
        try:
            async with httpx.AsyncClient(timeout=settings.cluster_timeout_s) as client:
                slots = await client.get(f"{base}/machines/{row.machine_id}/slots", headers=headers)
                slots.raise_for_status()
                body = slots.json()
        except Exception as exc:
            log.warning("slot sync skipped for %s: %s", row.machine_id, exc)
            continue
        slot_rows = body if isinstance(body, list) else body.get("slots") or body.get("items") or []
        await _replace_slots(session, row.machine_id, slot_rows)
        await hub.publish("slots", {"machine_id": row.machine_id, "slots": [_slot_dict(slot) for slot in slot_rows if isinstance(slot, dict)]})
    if changed:
        summaries = await _summaries(session, changed)
        await hub.publish("fleet", summaries)


async def rollup_agg(session: AsyncSession) -> None:
    """定时任务：把当前 5 分钟桶里新结束的测试记进 agg_5m。"""
    bucket = now_ms()
    bucket -= bucket % 300_000
    row = await session.get(Agg5mOrm, bucket)
    if row is None:
        row = Agg5mOrm(bucket=bucket, tests=0, passed=0, failed=0, aborted=0, rc_mean=0, dt01_mean=0)
        session.add(row)
    runs = (await session.execute(select(RunOrm).where(RunOrm.ended_at >= bucket, RunOrm.status != "RUNNING"))).scalars().all()
    if not runs:
        return
    row.tests = len(runs)
    row.passed = sum(1 for run in runs if run.passed is True)
    row.failed = sum(1 for run in runs if run.passed is False and run.status == "COMPLETED")
    row.aborted = sum(1 for run in runs if run.status in {"ABORTED", "FAULT"})
    rc_values = [run.rc for run in runs if run.rc is not None]
    dt_values = [run.dt01 for run in runs if run.dt01 is not None]
    row.rc_mean = round(sum(rc_values) / len(rc_values), 3) if rc_values else 0
    row.dt01_mean = round(sum(dt_values) / len(dt_values), 3) if dt_values else 0
    await hub.publish("agg_5m", {
        "bucket": row.bucket, "tests": row.tests, "passed": row.passed, "failed": row.failed,
        "aborted": row.aborted, "rc_mean": row.rc_mean, "dt01_mean": row.dt01_mean,
    })


async def scan_alarms(session: AsyncSession) -> None:
    """定时任务：根据机台和槽位状态生成告警，并触发归因。"""
    machines = (await session.execute(select(MachineOrm))).scalars().all()
    slots = (await session.execute(select(SlotOrm))).scalars().all()
    open_keys = {(row.machine_id, row.code, row.slot_index) for row in (await session.execute(select(AlarmOrm).where(AlarmOrm.acked.is_(False)))).scalars()}
    created: list[AlarmOrm] = []
    for machine in machines:
        if machine.status == "FAULT" and machine.alarm:
            created += _open(session, open_keys, machine.machine_id, None, "critical", "机台", machine.alarm.split(" · ")[0], machine.alarm)
        if machine.comm_status == "DISCONNECTED":
            created += _open(session, open_keys, machine.machine_id, None, "critical", "通信", "DISCONNECTED", f"{machine.machine_id} 通信断开")
        elif machine.comm_status == "DEGRADED" and settings.degraded_alarm:
            created += _open(session, open_keys, machine.machine_id, None, "major", "通信", "DEGRADED", f"{machine.machine_id} 通信降级：{machine.comm_note or '降级'}")
    for slot in slots:
        if slot.phase == "ERROR":
            created += _open(session, open_keys, slot.machine_id, slot.index, "major", "槽位", "SLOT_ERROR", slot.last_error or "槽位错误")
    for alarm in created:
        await build_attribution(session, alarm, "系统")
        await hub.publish("alarms", alarm_out(alarm_entity(alarm)).model_dump())


def _open(session, keys, machine_id, slot_index, level, source, code, message) -> list[AlarmOrm]:
    key = (machine_id, code, slot_index)
    if key in keys:
        return []
    keys.add(key)
    row = AlarmOrm(
        id=f"AL-{uuid4().hex[:8]}",
        time=now_ms(),
        level=level,
        machine_id=machine_id,
        slot_index=slot_index,
        source=source,
        code=code,
        message=message,
        acked=False,
    )
    session.add(row)
    return [row]


async def _touch(session: AsyncSession) -> None:
    stamp = now_ms()
    for machine in (await session.execute(select(MachineOrm))).scalars():
        machine.last_sync_at = stamp


async def _upsert_machine(session: AsyncSession, item: dict) -> MachineOrm:
    machine_id = str(item["machine_id"])
    row = await session.get(MachineOrm, machine_id)
    if row is None:
        row = MachineOrm(
            machine_id=machine_id,
            serial=item.get("serial") or machine_id,
            fixture=item.get("fixture") or "",
            holder=item.get("holder") or "",
            thermal_boards=item.get("thermal_boards") or "",
            plc=item.get("plc") or "INOVANCE",
            firmware=item.get("firmware") or "",
            slot_count=int(item.get("slot_count") or 0),
            status=item.get("status") or "READY",
            comm_status=item.get("comm_status") or "ONLINE",
            capability=item.get("capability") or {},
            last_sync_at=now_ms(),
            room_temp_c=float(item.get("room_temp_c") or 0),
        )
        session.add(row)
    for field in ("serial", "fixture", "holder", "thermal_boards", "plc", "firmware", "status", "comm_status", "comm_note", "alarm", "plan_id"):
        if field in item and item[field] is not None:
            setattr(row, field, item[field])
    if "slot_count" in item:
        row.slot_count = int(item["slot_count"])
    if "plan_version" in item:
        row.plan_version = item["plan_version"]
    if "speed" in item:
        row.speed = float(item["speed"])
    if "room_temp_c" in item:
        row.room_temp_c = float(item["room_temp_c"])
    if "capability" in item and isinstance(item["capability"], dict):
        row.capability = item["capability"]
    row.last_sync_at = now_ms()
    return row


async def _replace_slots(session: AsyncSession, machine_id: str, slots: list) -> None:
    existing = {row.index: row for row in (await session.execute(select(SlotOrm).where(SlotOrm.machine_id == machine_id))).scalars()}
    for item in slots:
        if not isinstance(item, dict) or "index" not in item:
            continue
        index = int(item["index"])
        row = existing.get(index)
        if row is None:
            row = SlotOrm(machine_id=machine_id, index=index, phase=item.get("phase") or "IDLE")
            session.add(row)
        for field in ("phase", "serial_number", "tests_done", "last_error", "power_w", "vacuum_kpa", "t0", "t1", "ta", "progress", "run_id"):
            if field in item:
                setattr(row, field, item[field])


async def _summaries(session: AsyncSession, machine_ids: list[str]) -> list[dict]:
    machines = await MachineService(session).list_machines()
    wanted = set(machine_ids)
    summaries = []
    for machine in machines:
        if machine.machine_id not in wanted:
            continue
        body = machine.model_dump()
        body.pop("capability", None)
        body.pop("slots", None)
        summaries.append(body)
    return summaries


def _slot_dict(item: dict) -> dict:
    return {
        "index": item.get("index"),
        "phase": item.get("phase"),
        "serial_number": item.get("serial_number"),
        "tests_done": item.get("tests_done", 0),
        "last_error": item.get("last_error") or "",
        "power_w": item.get("power_w", 0),
        "vacuum_kpa": item.get("vacuum_kpa", 0),
        "t0": item.get("t0", 0),
        "t1": item.get("t1", 0),
        "ta": item.get("ta", 0),
        "progress": item.get("progress", 0),
        "run_id": item.get("run_id"),
    }
