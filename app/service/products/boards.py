from app.core.errors import AppError
from app.service.machines.cluster import cluster_exchange

HIDDEN = {"grade", "quality", "contact_quality", "defects", "thermal_resistance"}


def public_board(item: dict) -> dict:
    return {key: value for key, value in item.items() if key not in HIDDEN}


def _rows(payload: dict | list) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    products = payload.get("products") or payload.get("items") or []
    return [item for item in products if isinstance(item, dict)]


async def list_boards(
    *,
    model: str | None,
    batch_id: str | None,
    state: str | None,
    golden: bool | None,
    cursor: str | None,
    limit: int,
) -> dict:
    payload = await cluster_exchange("GET", "/products")
    rows = [public_board(item) for item in _rows(payload)]
    if model is not None:
        rows = [item for item in rows if item.get("model") == model]
    if batch_id is not None:
        rows = [item for item in rows if item.get("batch_id") == batch_id]
    if state is not None:
        rows = [item for item in rows if item.get("state") == state]
    if golden is not None:
        rows = [item for item in rows if item.get("golden") is golden]
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    size = max(1, min(limit, 200))
    page = rows[offset : offset + size]
    next_cursor = str(offset + size) if offset + size < len(rows) else None
    return {"items": page, "total": len(rows), "next_cursor": next_cursor}


async def get_board(serial_number: str) -> dict:
    payload = await cluster_exchange("GET", f"/products/{serial_number}")
    if not isinstance(payload, dict):
        raise AppError(502, "CLUSTER_ERROR", "集群没有返回这片板的档案")
    return public_board(payload)


async def defect_kinds() -> dict:
    payload = await cluster_exchange("GET", "/defect-kinds")
    kinds = payload.get("kinds") if isinstance(payload, dict) else payload
    if not isinstance(kinds, list):
        raise AppError(502, "CLUSTER_ERROR", "集群没有返回缺陷目录")
    return {"kinds": kinds}


async def requeue(serial_number: str) -> dict:
    payload = await cluster_exchange("POST", f"/products/{serial_number}/requeue")
    if isinstance(payload, dict):
        return public_board(payload)
    return {"serial_number": serial_number, "state": "NEW"}
