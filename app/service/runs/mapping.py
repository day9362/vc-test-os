from dataclasses import asdict

from app.models.dto.run import RunDetailOut, RunOut
from app.models.entity.run import RunEntity
from app.models.orm.run import RunOrm


def run_entity(row: RunOrm) -> RunEntity:
    return RunEntity(
        run_id=row.run_id,
        machine_id=row.machine_id,
        slot_index=row.slot_index,
        serial_number=row.serial_number or "",
        plan_id=row.plan_id,
        plan_version=row.plan_version,
        status=row.status,
        passed=row.passed,
        fail_items=list(row.fail_items or []),
        keep_result=row.keep_result,
        rc=row.rc,
        dt01=row.dt01,
        batch_id=row.batch_id or "",
        ended_at=row.ended_at,
        result=dict(row.result or {}),
    )


def run_out(entity: RunEntity) -> RunOut:
    data = asdict(entity)
    data.pop("result", None)
    return RunOut.model_validate(data)


def run_detail_out(entity: RunEntity) -> RunDetailOut:
    return RunDetailOut.model_validate(asdict(entity))
