from app.models.dto.production import BatchOut, BatchStatOut, ProductModelOut, ProductionOut
from app.models.orm.production import BatchRecordOrm, ProductModelOrm, ProductionOrm


def model_out(row: ProductModelOrm) -> ProductModelOut:
    return ProductModelOut(model=row.model, resistance_mean=row.resistance_mean, resistance_sd=row.resistance_sd, power_w=row.power_w)


def batch_out(row: BatchRecordOrm) -> BatchOut:
    return BatchOut(
        batch_id=row.batch_id, model=row.model, count=row.count, defect_ratio=row.defect_ratio,
        batch_factor=row.batch_factor, remaining=row.remaining,
    )


def stat_out(row: BatchRecordOrm) -> BatchStatOut:
    state = row.state if row.state in {"running", "done", "stopped"} else "done"
    return BatchStatOut(
        batch_id=row.batch_id, model=row.model, count=row.count, tested=row.tested, passed=row.passed,
        failed=row.failed, aborted=row.aborted, plan_id=row.plan_id, plan_version=row.plan_version,
        machine_ids=list(row.machine_ids or []), started_at=row.started_at, ended_at=row.ended_at,
        state=state, rc_mean=row.rc_mean, rc_sd=row.rc_sd, top_fail=row.top_fail or "", eta_s=row.eta_s,
    )


def production_out(row: ProductionOrm) -> ProductionOut:
    return ProductionOut(
        batch_id=row.batch_id, queue_remaining=row.queue_remaining, plan_id=row.plan_id, plan_version=row.plan_version,
    )
