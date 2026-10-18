import math
from time import time

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.entity.user import UserEntity
from app.models.orm.alarm import AlarmOrm, AttributionOrm
from app.models.orm.machine import MachineOrm, SlotOrm
from app.models.orm.plan import PlanDispatchOrm
from app.models.orm.run import Agg5mOrm, RunOrm, RunSampleOrm
from app.models.orm.user import UserOrm
from app.repo.user_repo import UserRepo

TEMP = ["T0", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11", "T12", "T13", "T14", "Ta", "T_air", "T_motor_up", "T_motor_down"]
FORCE = [f"F{i}" for i in range(1, 15)]
CAPABILITY = {
    "temp_channels": TEMP,
    "force_channels": FORCE,
    "duration_low_s": 1,
    "duration_high_s": 600,
    "power_low_w": 0.1,
    "power_high_w": 10,
    "force_low_g": 20,
    "force_high_g": 300,
}
STATUSES = [
    ("READY", "ONLINE", "", ""),
    ("READY", "ONLINE", "", ""),
    ("READY", "ONLINE", "", ""),
    ("READY", "ONLINE", "", ""),
    ("FAULT", "ONLINE", "", "PLC_FAULT · PLC 无响应"),
    ("READY", "ONLINE", "", ""),
    ("READY", "ONLINE", "", ""),
    ("MAINTENANCE", "ONLINE", "", ""),
    ("READY", "ONLINE", "", ""),
    ("READY", "ONLINE", "", ""),
    ("READY", "DEGRADED", "丢包", ""),
    ("READY", "DISCONNECTED", "", ""),
]
PHASES = ["RESETTING", "PREHEATING", "WAITING_LOAD", "CLAMPING", "SAMPLING", "RECOVERING"]


def _now() -> int:
    return int(time() * 1000)


async def seed() -> None:
    async with SessionLocal() as session:
        exists = (await session.execute(select(func.count()).select_from(UserOrm))).scalar_one()
        if exists:
            return
        await UserRepo(session).add(UserEntity("limingyuan", "limingyuan", "李明远", "test", hash_password("changeme")))
        now = _now()
        _machines(session, now)
        _plan_history(session, now)
        _runs_and_agg(session, now)
        _alarms(session, now)
        await session.commit()


def _machines(session, now: int) -> None:
    for index, (status, comm, note, alarm) in enumerate(STATUSES, start=1):
        machine_id = f"M{index:02d}"
        hvp = index in (9, 10)
        plan_id = None if status == "MAINTENANCE" else ("PLAN-3f2c71d0" if hvp else "PLAN-592bbc46")
        plan_version = None if status == "MAINTENANCE" else (3 if hvp else 2)
        running = status == "READY" and comm != "DISCONNECTED"
        session.add(MachineOrm(
            machine_id=machine_id,
            serial=f"X9610_{index}#",
            fixture=f"513000{index:02d}",
            holder=f"V01_00{10 + index * 3:02d}",
            thermal_boards=f"TM_BOX_V3_56F{index}001;TM_BOX_V3_56F{index}5001",
            plc="INOVANCE" if index % 2 else "OMRON",
            firmware="VC_BASE_BOX_V2" if index == 12 else "VC_BASE_BOX_V3",
            slot_count=10,
            status=status,
            comm_status=comm,
            comm_note=note,
            speed=1,
            room_temp_c=round(23.6 + index * 0.11, 2),
            alarm=alarm,
            plan_id=plan_id,
            plan_version=plan_version,
            capability=CAPABILITY,
            last_sync_at=now,
        ))
        for slot in range(1, 11):
            phase = "IDLE"
            if running:
                phase = PHASES[(index + slot) % len(PHASES)]
            if index == 3 and slot == 7:
                phase = "ERROR"
            if index == 5 and slot <= 2:
                phase = "ERROR"
            sampling = phase == "SAMPLING"
            session.add(SlotOrm(
                machine_id=machine_id,
                index=slot,
                phase=phase,
                serial_number=None if phase in {"IDLE", "RESETTING", "PREHEATING"} else f"SN-{machine_id}-{slot:02d}",
                tests_done=1800 + index * 30 + slot,
                last_error="VACUUM_LEAK · 真空未到位（-44.8 kPa）" if phase == "ERROR" and index == 3 else ("PLC 无响应" if phase == "ERROR" else ""),
                power_w=3.5 if sampling and hvp else (2.5 if sampling else 0),
                vacuum_kpa=-85 if phase in {"WAITING_LOAD", "CLAMPING", "SAMPLING"} else -2,
                t0=43.2 if sampling else 45.0,
                t1=40.8 if sampling else 24.6,
                ta=round(24 + index * 0.08, 2),
                progress=60 if sampling else 0,
                run_id=f"R-{machine_id}-{slot}-seed" if phase != "IDLE" else None,
            ))
            if sampling:
                _curve(session, machine_id, slot, hvp)


def _curve(session, machine_id: str, slot: int, hvp: bool) -> None:
    run_id = f"R-{machine_id}-{slot}-seed"
    power = 3.5 if hvp else 2.5
    rc = 5.18 if hvp else 4.77
    session.add(RunOrm(
        run_id=run_id,
        machine_id=machine_id,
        slot_index=slot,
        serial_number=f"SN-{machine_id}-{slot:02d}",
        plan_id="PLAN-3f2c71d0" if hvp else "PLAN-592bbc46",
        plan_version=3 if hvp else 2,
        status="RUNNING",
        passed=None,
        fail_items=[],
        keep_result=True,
        rc=rc,
        dt01=2.9 if hvp else 2.07,
        batch_id="B-tb172-seed",
        ended_at=_now(),
        result={"duration_s": 180, "deltas": {"Rc": rc, "Temp_T0-T1": 2.9 if hvp else 2.07}},
    ))
    for step in range(0, 61, 3):
        k = 1 - math.exp(-step / 28)
        ta = 24.2
        t1 = ta + (5.18 if hvp else 4.77) * power * k
        t0 = t1 + (2.9 if hvp else 2.07) * (0.4 + 0.6 * k)
        session.add(RunSampleOrm(run_id=run_id, t_s=step, t0=round(t0, 3), t1=round(t1, 3), ta=ta, power_w=power))


def _plan_history(session, now: int) -> None:
    hour = 3_600_000
    for index in range(1, 13):
        machine_id = f"M{index:02d}"
        hvp = index in (9, 10)
        plan_id = "PLAN-3f2c71d0" if hvp else "PLAN-592bbc46"
        name = "HVP 3.5W 标准测试" if hvp else "45度测3分钟"
        current = 3 if hvp else 2
        session.add(PlanDispatchOrm(
            machine_id=machine_id, plan_id=plan_id, name=name, version=current - 1,
            started_at=now - 6 * 24 * hour, ended_at=now - 30 * hour,
        ))
        if index == 8:
            continue
        session.add(PlanDispatchOrm(
            machine_id=machine_id, plan_id=plan_id, name=name, version=current,
            started_at=now - int(5.2 * hour), ended_at=None,
        ))


def _runs_and_agg(session, now: int) -> None:
    bucket = now - (now % 300_000) - 95 * 300_000
    for offset in range(96):
        tests = 48 + (offset % 7)
        failed = 1 if offset % 11 else 2
        aborted = 1 if offset % 17 == 0 else 0
        passed = tests - failed - aborted
        session.add(Agg5mOrm(
            bucket=bucket + offset * 300_000,
            tests=tests,
            passed=passed,
            failed=failed,
            aborted=aborted,
            rc_mean=round(4.80 + (offset % 5) * 0.01, 3),
            dt01_mean=round(2.05 + (offset % 4) * 0.02, 3),
        ))
    for index in range(1, 13):
        if index in (8, 12):
            continue
        machine_id = f"M{index:02d}"
        bias = 0.09 if index == 7 else (-0.05 if index == 3 else 0)
        for n in range(40):
            rc = round(4.77 + bias + ((n % 5) - 2) * 0.02, 3)
            passed = rc < 5.05
            session.add(RunOrm(
                run_id=f"R-{machine_id}-{n:03d}",
                machine_id=machine_id,
                slot_index=(n % 10) + 1,
                serial_number=f"SN-{machine_id}-{n:04d}",
                plan_id="PLAN-3f2c71d0" if index in (9, 10) else "PLAN-592bbc46",
                plan_version=3 if index in (9, 10) else 2,
                status="COMPLETED",
                passed=passed,
                fail_items=[] if passed else ["Temp_T0-T1"],
                keep_result=True,
                rc=rc,
                dt01=round(2.07 + bias, 3),
                batch_id="B-tb172-seed",
                ended_at=now - n * 60_000 - index * 1000,
                result={"deltas": {"Rc": rc, "Temp_T0-T1": round(2.07 + bias, 3)}},
            ))


def _alarms(session, now: int) -> None:
    rows = [
        ("AL-10418", now - 20 * 60_000, "critical", "M05", None, "机台", "PLC_FAULT", "PLC 无响应"),
        ("AL-10419", now - 15 * 60_000, "critical", "M12", None, "通信", "DISCONNECTED", "M12 通信断开"),
        ("AL-10420", now - 12 * 60_000, "major", "M11", None, "通信", "DEGRADED", "M11 通信降级：丢包"),
        ("AL-10421", now - 8 * 60_000, "major", "M03", 7, "槽位", "VACUUM_LEAK", "真空未到位（-44.8 kPa）"),
        ("AL-10422", now - 5 * 60_000, "minor", "M07", 4, "判定", "Temp_T1-T14", "Temp_T1-T14 接近上限（3.8 / 4.0 ℃）"),
        ("AL-10423", now - 3 * 60_000, "minor", "M07", None, "漂移", "EQUIPMENT_ANOMALY", "T1 通道漂移 +0.18 ℃"),
    ]
    for row in rows:
        session.add(AlarmOrm(id=row[0], time=row[1], level=row[2], machine_id=row[3], slot_index=row[4], source=row[5], code=row[6], message=row[7], acked=False))
    session.add(AttributionOrm(
        alarm_id="AL-10423",
        status="done",
        category="equipment",
        confidence=0.86,
        summary="M07 T1 通道线性漂移 +0.18 ℃，同批次在其它机台正常，判断为设备异常",
        evidence=["同批次其它机台良率正常", "标准样品复测 T1 偏差 +0.182 ℃"],
        suggestion="写入 T1 补偿 −0.18 ℃ 后用标准样品复测",
        model="rule",
        created_at=now - 3 * 60_000,
    ))
