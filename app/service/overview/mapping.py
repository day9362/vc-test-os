from dataclasses import asdict

from app.models.dto.alarm import AlarmOut, AttributionOut
from app.models.dto.machine import MachineOut
from app.models.entity.alarm import AlarmEntity, AttributionEntity
from app.models.entity.machine import CapabilityEntity, MachineEntity, SlotEntity, YieldRecent
from app.models.orm.alarm import AlarmOrm, AttributionOrm
from app.models.orm.machine import MachineOrm, SlotOrm


def machine_entity(row: MachineOrm, slots: list[SlotOrm], passed: list[bool | None]) -> MachineEntity:
    capability = row.capability or {}
    return MachineEntity(
        machine_id=row.machine_id,
        serial=row.serial,
        fixture=row.fixture,
        holder=row.holder,
        thermal_boards=row.thermal_boards,
        plc=row.plc,
        firmware=row.firmware,
        slot_count=row.slot_count,
        status=row.status,
        comm_status=row.comm_status,
        comm_note=row.comm_note or "",
        speed=row.speed,
        room_temp_c=row.room_temp_c,
        alarm=row.alarm or "",
        plan_id=row.plan_id,
        plan_version=row.plan_version,
        capability=CapabilityEntity(
            temp_channels=list(capability.get("temp_channels") or []),
            force_channels=list(capability.get("force_channels") or []),
            duration_low_s=capability.get("duration_low_s", 0),
            duration_high_s=capability.get("duration_high_s", 0),
            power_low_w=capability.get("power_low_w", 0),
            power_high_w=capability.get("power_high_w", 0),
            force_low_g=capability.get("force_low_g", 0),
            force_high_g=capability.get("force_high_g", 0),
        ),
        slots=[SlotEntity(
            index=slot.index,
            phase=slot.phase,
            serial_number=slot.serial_number,
            tests_done=slot.tests_done,
            last_error=slot.last_error or "",
            power_w=slot.power_w,
            vacuum_kpa=slot.vacuum_kpa,
            t0=slot.t0,
            t1=slot.t1,
            ta=slot.ta,
            progress=slot.progress,
            run_id=slot.run_id,
        ) for slot in slots],
        last_sync_at=row.last_sync_at,
        yield_recent=YieldRecent(n=len(passed), passed=sum(1 for item in passed if item)),
    )


def machine_out(entity: MachineEntity) -> MachineOut:
    return MachineOut.model_validate(asdict(entity))


def alarm_entity(row: AlarmOrm) -> AlarmEntity:
    return AlarmEntity(
        id=row.id,
        time=row.time,
        level=row.level,
        machine_id=row.machine_id,
        slot_index=row.slot_index,
        source=row.source,
        code=row.code,
        message=row.message,
        acked=row.acked,
        acked_by=row.acked_by,
        acked_at=row.acked_at,
    )


def alarm_out(entity: AlarmEntity) -> AlarmOut:
    return AlarmOut.model_validate(asdict(entity))


def attribution_out(row: AttributionOrm) -> AttributionOut:
    entity = AttributionEntity(
        alarm_id=row.alarm_id,
        status=row.status,
        category=row.category,
        confidence=row.confidence,
        summary=row.summary or "",
        evidence=list(row.evidence or []),
        suggestion=row.suggestion or "",
        model=row.model or "",
        created_at=row.created_at,
    )
    return AttributionOut.model_validate(asdict(entity))
