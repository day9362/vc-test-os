from app.service.realtime.hub import hub
from app.service.realtime.watch import state


async def push_batch(batch: dict) -> None:
    """批次进度变化时由写操作触发。批次表落地前也可以直接调用。"""
    await hub.publish("batches", batch)


async def push_production(production: dict | None) -> None:
    """连续生产开始、停止或完成时触发。没有生产任务时 data 为 null。"""
    marker = None if production is None else (production.get("batch_id"), production.get("queue_remaining"), production.get("plan_id"), production.get("plan_version"))
    if state.production == marker and state.ready:
        return
    state.production = marker
    await hub.publish("production", production)
