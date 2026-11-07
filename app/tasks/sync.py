import asyncio
import json
import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.config import settings
from app.core.errors import AppError
from app.core.redis import redis_client
from app.models.orm.alarm import AlarmOrm
from app.models.orm.machine import MachineOrm, SlotOrm
from app.models.orm.run import Agg5mOrm, RunOrm
from app.service.compensation.cluster import cluster_json
from app.service.settings.cluster_policy import async_send, request_timeout
from app.service.overview.attribution import build_attribution
from app.service.overview.hub import hub
from app.service.overview.machine_service import MachineService
from app.service.overview.mapping import alarm_entity, alarm_out
from app.service.overview.rules import escalate_alarm, load_alarm_rules, matched_we_rules, we_message
from app.service.runs.cluster_ingest import fleet_machine_ids, refresh_fleet

log = logging.getLogger(__name__)


async def sync_cluster(session: AsyncSession) -> None:
    """定时任务：按机群状态的间隔拉取 /fleet。槽位和机台详情各自另有任务。"""
    base = settings.cluster_base_url.rstrip("/")
    if not base:
        await _touch(session)
        return
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    try:
        fleet = await async_send("GET", f"{base}/fleet", timeout=request_timeout(), headers=headers)
        fleet.raise_for_status()
        payload = fleet.json()
        machines = payload if isinstance(payload, list) else payload.get("machines") or payload.get("items") or []
        changed = []
        for item in machines:
            if not isinstance(item, dict) or "machine_id" not in item:
                continue
            row = await _upsert_machine(session, item)
            changed.append(row.machine_id)
        if changed:
            summaries = await _summaries(session, changed)
            await hub.publish("fleet", summaries)
    except Exception:
        raise


async def _fleet_rows(session: AsyncSession) -> list[MachineOrm]:
    ids = fleet_machine_ids() or await refresh_fleet()
    if not ids:
        return []
    return list((await session.execute(select(MachineOrm).where(MachineOrm.machine_id.in_(ids)))).scalars().all())


async def sync_slots(session: AsyncSession) -> None:
    """按槽位实时的间隔拉取每台在线机台的槽位。通信断开的机台跳过。"""
    base = settings.cluster_base_url.rstrip("/")
    if not base:
        return
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    timeout = request_timeout(slot=True)
    machines = [row for row in await _fleet_rows(session) if row.comm_status != "DISCONNECTED"]

    async def fetch(machine_id: str):
        try:
            response = await async_send("GET", f"{base}/machines/{machine_id}/slots", timeout=timeout, headers=headers)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            log.warning("slot sync skipped for %s: %s", machine_id, exc)
            return machine_id, None
        rows = body if isinstance(body, list) else body.get("slots") or body.get("items") or []
        return machine_id, rows

    fetched = await asyncio.gather(*(fetch(row.machine_id) for row in machines))
    for machine_id, slot_rows in fetched:
        if slot_rows is None:
            continue
        await _replace_slots(session, machine_id, slot_rows)
        await hub.publish(
            "slots",
            {"machine_id": machine_id, "slots": [_slot_dict(slot) for slot in slot_rows if isinstance(slot, dict)]},
        )


async def sync_machine_details(session: AsyncSession) -> None:
    """按机台详情的间隔拉取配置、报警、室温和槽位数。"""
    base = settings.cluster_base_url.rstrip("/")
    if not base:
        return
    headers = {"Authorization": f"Bearer {settings.cluster_token}"} if settings.cluster_token else {}
    timeout = request_timeout()
    machines = [row for row in await _fleet_rows(session) if row.comm_status != "DISCONNECTED"]
    changed = []

    async def fetch(machine_id: str):
        try:
            response = await async_send("GET", f"{base}/machines/{machine_id}", timeout=timeout, headers=headers)
            response.raise_for_status()
            payload = response.json() if response.content else {}
        except Exception as exc:
            log.warning("machine detail sync skipped for %s: %s", machine_id, exc)
            return machine_id, None
        return machine_id, payload if isinstance(payload, dict) else None

    fetched = await asyncio.gather(*(fetch(row.machine_id) for row in machines))
    for machine_id, payload in fetched:
        if not payload:
            continue
        payload["machine_id"] = machine_id
        await _upsert_machine(session, payload)
        if payload.get("slot_count") is not None:
            await _prune_slots(session, machine_id, int(payload["slot_count"]))
        changed.append(machine_id)
    if changed:
        await hub.publish("fleet", await _summaries(session, changed))


async def sync_calib(session: AsyncSession) -> None:
    """按补偿与漂移的间隔拉取每台在线机台，供设备配置页直接读。"""
    machines = [row for row in await _fleet_rows(session) if row.comm_status != "DISCONNECTED"]
    if not machines:
        return
    redis = redis_client()
    synced = 0
    for row in machines:
        try:
            compensation = await cluster_json("GET", f"/machines/{row.machine_id}/compensation")
            drifts = await cluster_json("GET", f"/machines/{row.machine_id}/drifts")
        except AppError as exc:
            log.warning("calib sync skipped for %s: %s", row.machine_id, exc.message)
            continue
        await redis.set(f"sync:comp:{row.machine_id}", json.dumps(compensation), ex=180)
        await redis.set(f"sync:drift:{row.machine_id}", json.dumps(drifts), ex=180)
        synced += 1
    if synced == 0:
        raise RuntimeError("补偿与漂移没有同步到")


async def rollup_agg(session: AsyncSession) -> None:
    """定时任务：把当前 5 分钟桶里新结束的测试记进 agg_5m。"""
    bucket = now_ms()
    bucket -= bucket % 300_000
    runs = (await session.execute(select(RunOrm).where(RunOrm.ended_at >= bucket, RunOrm.status != "RUNNING"))).scalars().all()
    if not runs:
        return
    row = await session.get(Agg5mOrm, bucket)
    if row is None:
        row = Agg5mOrm(bucket=bucket, tests=0, passed=0, failed=0, aborted=0, rc_mean=0, dt01_mean=0)
        session.add(row)
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
    machines = list((await session.execute(select(MachineOrm))).scalars().all())
    slots = list((await session.execute(select(SlotOrm))).scalars().all())
    fleet = fleet_machine_ids() or await refresh_fleet()
    if fleet:
        allowed = set(fleet)
        machines = [machine for machine in machines if machine.machine_id in allowed]
        slots = [slot for slot in slots if slot.machine_id in allowed]
    open_rows = list((await session.execute(select(AlarmOrm).where(AlarmOrm.acked.is_(False)))).scalars())
    open_keys = {(row.machine_id, row.code, row.slot_index) for row in open_rows}
    rules = await load_alarm_rules(session)
    stamp = now_ms()
    escalated = [row for row in open_rows if escalate_alarm(row, stamp, rules.ack_timeout_min)]
    created: list[AlarmOrm] = []
    for machine in machines:
        if machine.status == "FAULT" and machine.alarm:
            created += _open(session, open_keys, machine.machine_id, None, "critical", "机台", machine.alarm.split(" · ")[0], machine.alarm)
        if machine.comm_status == "DISCONNECTED":
            created += _open(session, open_keys, machine.machine_id, None, "critical", "通信", "DISCONNECTED", f"{machine.machine_id} 通信断开")
        elif machine.comm_status == "DEGRADED" and rules.degraded_alarm:
            created += _open(session, open_keys, machine.machine_id, None, "major", "通信", "DEGRADED", f"{machine.machine_id} 通信降级：{machine.comm_note or '降级'}")
    for slot in slots:
        if slot.phase == "ERROR":
            created += _open(session, open_keys, slot.machine_id, slot.index, "major", "槽位", "SLOT_ERROR", slot.last_error or "槽位错误")
        if rules.sentinel_as_data_anomaly:
            for channel, value in (("T0", slot.t0), ("T1", slot.t1), ("Ta", slot.ta)):
                code = _sentinel_code(value)
                if code:
                    created += _open(session, open_keys, slot.machine_id, slot.index, "minor", "数据", code, f"{channel} 读数 {_plain(value)}（哨兵值）")
    created += await _drift_alarms(session, open_keys, rules.drift_c)
    created += await _trend_alarms(session, open_keys, rules.we_rules)
    created += await _consecutive_alarms(session, open_keys)
    created += _ambient_alarms(session, machines, open_keys)
    for alarm in created:
        await build_attribution(session, alarm, "系统", automatic=True)
    for alarm in [*escalated, *created]:
        await hub.publish("alarms", alarm_out(alarm_entity(alarm)).model_dump())


PLAN_AMBIENT = {"PLAN-592bbc46": (23.0, 27.0), "PLAN-3f2c71d0": (23.0, 27.0)}
SENTINELS = {99999: "SENSOR_99999", 9999: "SENSOR_9999", -1: "SENSOR_NO_RESPONSE", -2: "SENSOR_UNPARSEABLE"}


def _plain(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _sentinel_code(value: float) -> str | None:
    if not float(value).is_integer():
        return None
    return SENTINELS.get(int(value))


def _ambient_alarms(session, machines, keys) -> list[AlarmOrm]:
    created: list[AlarmOrm] = []
    for machine in machines:
        bounds = PLAN_AMBIENT.get(machine.plan_id or "")
        if bounds is None:
            continue
        low, high = bounds
        if low <= machine.room_temp_c <= high:
            continue
        created += _open(
            session, keys, machine.machine_id, None, "major", "机台", "AMBIENT_RANGE",
            f"房间温度 {machine.room_temp_c:.1f} ℃ 超出方案范围 {low:.0f}–{high:.0f} ℃",
        )
    return created


async def _drift_alarms(session: AsyncSession, keys, drift_c: float) -> list[AlarmOrm]:
    grouped = await _dt01_groups(session)
    created: list[AlarmOrm] = []
    for machine_id, samples in grouped.items():
        if len(samples) < 5:
            continue
        baseline = sorted(samples[1:])
        mid = len(baseline) // 2
        median = baseline[mid] if len(baseline) % 2 else (baseline[mid - 1] + baseline[mid]) / 2
        estimate = samples[0] - median
        if abs(estimate) <= drift_c:
            continue
        created += _open(
            session, keys, machine_id, None, "major", "漂移", "EQUIPMENT_ANOMALY",
            f"T0-T1 通道漂移 {estimate:+.3f} ℃",
        )
    return created


async def _trend_alarms(session: AsyncSession, keys, enabled: tuple[str, ...]) -> list[AlarmOrm]:
    if not enabled:
        return []
    grouped = await _dt01_groups(session)
    created: list[AlarmOrm] = []
    for machine_id, samples in grouped.items():
        for rule in matched_we_rules(samples, enabled):
            created += _open(session, keys, machine_id, None, "major", "趋势", rule, we_message(rule, samples[0]))
    return created


async def _dt01_groups(session: AsyncSession) -> dict[str, list[float]]:
    rows = (await session.execute(
        select(RunOrm.machine_id, RunOrm.dt01).where(RunOrm.dt01.is_not(None)).order_by(RunOrm.ended_at.desc()).limit(4000)
    )).all()
    grouped: dict[str, list[float]] = {}
    for machine_id, dt01 in rows:
        bucket = grouped.setdefault(machine_id, [])
        if len(bucket) < 30:
            bucket.append(float(dt01))
    return grouped


async def _consecutive_alarms(session: AsyncSession, keys) -> list[AlarmOrm]:
    rows = (await session.execute(
        select(RunOrm.machine_id, RunOrm.passed, RunOrm.fail_items)
        .where(RunOrm.status == "COMPLETED", RunOrm.passed.is_not(None))
        .order_by(RunOrm.ended_at.desc())
        .limit(4000)
    )).all()
    grouped: dict[str, list] = {}
    for machine_id, passed, fail_items in rows:
        bucket = grouped.setdefault(machine_id, [])
        if len(bucket) < 3:
            bucket.append((passed, fail_items or []))
    created: list[AlarmOrm] = []
    for machine_id, samples in grouped.items():
        if len(samples) < 3 or any(passed for passed, _items in samples):
            continue
        item = samples[0][1][0] if samples[0][1] else "CONSECUTIVE_FAIL"
        created += _open(session, keys, machine_id, None, "major", "判定", str(item), f"连续 3 片 {item} 不合格")
    return created


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
    """用集群当前槽位覆盖本地。集群缩容后必须删掉多余槽，否则 Agent 会按脏数据去中止不存在的槽，集群直接 500。"""
    existing = {row.index: row for row in (await session.execute(select(SlotOrm).where(SlotOrm.machine_id == machine_id))).scalars()}
    seen: set[int] = set()
    for item in slots:
        if not isinstance(item, dict) or "index" not in item:
            continue
        index = int(item["index"])
        seen.add(index)
        row = existing.get(index)
        if row is None:
            row = SlotOrm(machine_id=machine_id, index=index, phase=item.get("phase") or "IDLE")
            session.add(row)
        for field in ("phase", "serial_number", "tests_done", "last_error", "power_w", "vacuum_kpa", "t0", "t1", "ta", "progress", "run_id"):
            if field in item:
                setattr(row, field, item[field])
    for index, row in existing.items():
        if index not in seen:
            await session.delete(row)
    machine = await session.get(MachineOrm, machine_id)
    if machine is not None and seen:
        machine.slot_count = len(seen)


async def _prune_slots(session: AsyncSession, machine_id: str, slot_count: int) -> None:
    if slot_count <= 0:
        return
    rows = (await session.execute(select(SlotOrm).where(SlotOrm.machine_id == machine_id, SlotOrm.index > slot_count))).scalars().all()
    for row in rows:
        await session.delete(row)


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
