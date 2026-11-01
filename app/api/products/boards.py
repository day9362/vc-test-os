from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.entity.user import UserEntity
from app.repo.audit_repo import AuditRepo
from app.service.products.boards import defect_kinds, get_board, list_boards, requeue

router = APIRouter(tags=["products"])


@router.get("/products")
async def products(
    model: str | None = None,
    batch_id: str | None = None,
    state: str | None = None,
    golden: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    _: object = Depends(current_user),
) -> dict:
    return await list_boards(model=model, batch_id=batch_id, state=state, golden=golden, cursor=cursor, limit=limit)


@router.get("/products/{serial_number}")
async def product(serial_number: str, _: object = Depends(current_user)) -> dict:
    return await get_board(serial_number)


@router.get("/defect-kinds")
async def kinds(_: object = Depends(current_user)) -> dict:
    return await defect_kinds()


@router.post("/products/{serial_number}/requeue")
async def requeue_board(
    serial_number: str,
    user: UserEntity = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    body = await requeue(serial_number)
    AuditRepo(session).record(user.user_id, "product.requeue", "", {"serial_number": serial_number}, body)
    await session.commit()
    return body
