from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.database import get_session
from app.models.dto.search import SearchOut
from app.service.search_service import SearchService

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchOut)
async def search(
    q: str = Query(default=""),
    limit: int = Query(default=10),
    _: object = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SearchOut:
    return await SearchService(session).search(q, limit)
