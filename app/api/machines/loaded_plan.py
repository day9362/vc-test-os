from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.core.errors import AppError
from app.service.machines.cluster import cluster_exchange

router = APIRouter(tags=["machines"])


@router.get("/machines/{machine_id}/loaded-plan")
async def loaded_plan(machine_id: str, _: object = Depends(current_user)) -> dict:
    try:
        payload = await cluster_exchange("GET", f"/machines/{machine_id}/plan")
    except AppError as exc:
        if exc.status == 404:
            return {"machine_id": machine_id, "loaded": False, "plan": None}
        raise
    plan = payload if isinstance(payload, dict) else None
    return {"machine_id": machine_id, "loaded": bool(plan), "plan": plan}
