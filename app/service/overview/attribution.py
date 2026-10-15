from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.models.orm.alarm import AiCallOrm, AlarmOrm, AttributionOrm
from app.repo.alarm_repo import AlarmRepo

CATEGORY = {"机台": "equipment", "槽位": "equipment", "漂移": "equipment", "判定": "product", "通信": "communication", "数据": "data"}


async def build_attribution(session: AsyncSession, alarm: AlarmOrm, actor: str) -> AttributionOrm:
    category = CATEGORY.get(alarm.source, "equipment")
    summary = f"{alarm.machine_id} {alarm.code}：{alarm.message}"
    suggestion = "先确认告警，再按设备配置里的补偿或复位处理"
    if alarm.code == "EQUIPMENT_ANOMALY":
        summary = f"{alarm.machine_id} 通道漂移超过阈值，同批次其它机台未出现同样偏差，判断为设备异常"
        suggestion = "按偏差写入补偿后，用标准样品复测"
    row = await AlarmRepo(session).attribution(alarm.id)
    stamp = now_ms()
    if row is None:
        row = AttributionOrm(alarm_id=alarm.id, created_at=stamp)
        session.add(row)
    row.status = "done"
    row.category = category
    row.confidence = 0.8
    row.summary = summary
    row.evidence = [alarm.message, f"来源 {alarm.source}，级别 {alarm.level}"]
    row.suggestion = suggestion
    row.model = "rule"
    row.created_at = stamp
    session.add(AiCallOrm(
        id=f"call-{uuid4().hex[:8]}",
        time=stamp,
        module="anomaly",
        user=actor,
        model="rule",
        input_tokens=0,
        output_tokens=0,
        latency_ms=1,
        ok=True,
        ref={"alarm_id": alarm.id},
    ))
    return row
