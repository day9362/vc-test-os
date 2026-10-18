from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.models.orm.alarm import AlarmOrm
from app.models.orm.run import Agg5mOrm, RunOrm
from app.service.overview.machine_service import MachineService
from app.service.overview.mapping import alarm_entity, alarm_out
from app.service.realtime.hub import hub

FINISHED = {"COMPLETED", "ABORTED", "FAULT"}


@dataclass
class WatchState:
    ready: bool = False
    machines: dict[str, tuple] = field(default_factory=dict)
    slots: dict[str, tuple] = field(default_factory=dict)
    runs: set[str] = field(default_factory=set)
    production: tuple | None = None
    alarms: dict[str, tuple] = field(default_factory=dict)
    aggs: dict[int, tuple] = field(default_factory=dict)
    sampling_at: dict[str, int] = field(default_factory=dict)


state = WatchState()


def reset_state() -> None:
    global state
    state = WatchState()


async def watch_changes(session: AsyncSession) -> None:
    """定时比对库内快照，只推送有变化的主题。采样中的槽位每秒推一次。"""
    machines = await MachineService(session).list_machines()
    alarms = list((await session.execute(select(AlarmOrm).order_by(AlarmOrm.time.desc()).limit(200))).scalars().all())
    aggs = list((await session.execute(select(Agg5mOrm).order_by(Agg5mOrm.bucket.desc()).limit(3))).scalars().all())
    runs = list((await session.execute(
        select(RunOrm).where(RunOrm.status.in_(FINISHED)).order_by(RunOrm.ended_at.desc()).limit(200)
    )).scalars().all())
    if not state.ready:
        _remember(machines, alarms, aggs, runs)
        state.ready = True
        return
    await _fleet_and_slots(machines)
    await _alarms(alarms)
    await _aggs(aggs)
    await _runs(runs)


def _remember(machines, alarms, aggs, runs) -> None:
    for machine in machines:
        state.machines[machine.machine_id] = _machine_key(machine)
        state.slots[machine.machine_id] = _slot_key(machine)
    for alarm in alarms:
        state.alarms[alarm.id] = _alarm_key(alarm)
    for row in aggs:
        state.aggs[row.bucket] = _agg_key(row)
    state.runs.update(run.run_id for run in runs)


async def _fleet_and_slots(machines) -> None:
    changed = []
    now = now_ms()
    for machine in machines:
        key = _machine_key(machine)
        if state.machines.get(machine.machine_id) != key:
            state.machines[machine.machine_id] = key
            body = machine.model_dump()
            body.pop("capability", None)
            body.pop("slots", None)
            changed.append(body)
        slot_key = _slot_key(machine)
        sampling = any(slot.phase == "SAMPLING" for slot in machine.slots)
        due = sampling and now - state.sampling_at.get(machine.machine_id, 0) >= 1000
        if state.slots.get(machine.machine_id) != slot_key or due:
            state.slots[machine.machine_id] = slot_key
            if sampling:
                state.sampling_at[machine.machine_id] = now
            await hub.publish("slots", {"machine_id": machine.machine_id, "slots": [slot.model_dump() for slot in machine.slots]})
    if changed:
        await hub.publish("fleet", changed)


async def _alarms(alarms) -> None:
    for alarm in alarms:
        key = _alarm_key(alarm)
        if state.alarms.get(alarm.id) == key:
            continue
        state.alarms[alarm.id] = key
        await hub.publish("alarms", alarm_out(alarm_entity(alarm)).model_dump())


async def _aggs(aggs) -> None:
    for row in aggs:
        key = _agg_key(row)
        if state.aggs.get(row.bucket) == key:
            continue
        state.aggs[row.bucket] = key
        await hub.publish("agg_5m", {
            "bucket": row.bucket,
            "tests": row.tests,
            "passed": row.passed,
            "failed": row.failed,
            "aborted": row.aborted,
            "rc_mean": row.rc_mean,
            "dt01_mean": row.dt01_mean,
        })


async def _runs(runs) -> None:
    for run in runs:
        if run.run_id in state.runs:
            continue
        state.runs.add(run.run_id)
        await hub.publish("runs", {
            "run_id": run.run_id,
            "machine_id": run.machine_id,
            "slot_index": run.slot_index,
            "serial_number": run.serial_number,
            "plan_id": run.plan_id,
            "plan_version": run.plan_version,
            "status": run.status,
            "passed": run.passed,
            "fail_items": list(run.fail_items or []),
            "keep_result": run.keep_result,
            "rc": run.rc,
            "dt01": run.dt01,
            "batch_id": run.batch_id,
            "ended_at": run.ended_at,
        })


def _machine_key(machine) -> tuple:
    return (
        machine.status, machine.comm_status, machine.comm_note, machine.alarm,
        machine.plan_id, machine.plan_version, machine.room_temp_c, machine.speed,
    )


def _slot_key(machine) -> tuple:
    return tuple(
        (slot.index, slot.phase, slot.serial_number, slot.tests_done, slot.last_error, slot.power_w, slot.vacuum_kpa, slot.t0, slot.t1, slot.ta, slot.progress, slot.run_id)
        for slot in machine.slots
    )


def _alarm_key(alarm: AlarmOrm) -> tuple:
    return (alarm.acked, alarm.level, alarm.message, alarm.acked_at)


def _agg_key(row: Agg5mOrm) -> tuple:
    return (row.tests, row.passed, row.failed, row.aborted, row.rc_mean, row.dt01_mean)
