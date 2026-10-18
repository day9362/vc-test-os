from app.models.dto.test_plan import PlanItemOut, PlanMetaOut, PlanOut
from app.models.entity.test_plan import LimitEntity, PlanEntity
from app.models.orm.test_plan import TestPlanOrm


def entity_of(row: TestPlanOrm, versions: list[int]) -> PlanEntity:
    return PlanEntity(
        plan_id=row.plan_id,
        name=row.name,
        version=row.version,
        start_temp_c=row.start_temp_c,
        duration_s=row.duration_s,
        sample_period_s=row.sample_period_s,
        power_w=row.power_w,
        force_g=row.force_g,
        orientation=row.orientation,
        overtemp_c=row.overtemp_c,
        ambient_low_c=row.ambient_low_c,
        ambient_high_c=row.ambient_high_c,
        limits=[LimitEntity(
            item=item.get("item", ""),
            low=item.get("low"),
            high=item.get("high"),
            unit=item.get("unit") or "",
            skipped=bool(item.get("skipped")),
        ) for item in (row.limits or [])],
        author=row.author,
        source=row.source,
        draft=row.draft,
        updated_at=row.updated_at,
        versions=versions,
    )


def item_out(entity: PlanEntity) -> PlanItemOut:
    plan = PlanOut(
        plan_id=entity.plan_id,
        name=entity.name,
        version=entity.version,
        start_temp_c=entity.start_temp_c,
        duration_s=entity.duration_s,
        sample_period_s=entity.sample_period_s,
        power_w=entity.power_w,
        force_g=entity.force_g,
        orientation=entity.orientation,
        overtemp_c=entity.overtemp_c,
        ambient_low_c=entity.ambient_low_c,
        ambient_high_c=entity.ambient_high_c,
        limits=[{
            "item": limit.item,
            "low": limit.low,
            "high": limit.high,
            "unit": limit.unit,
            "skipped": limit.skipped,
        } for limit in entity.limits],
    )
    meta = PlanMetaOut(
        plan_id=entity.plan_id,
        versions=entity.versions,
        updated_at=entity.updated_at,
        author=entity.author,
        source=entity.source,
        draft=entity.draft,
    )
    return PlanItemOut(plan=plan, meta=meta)
