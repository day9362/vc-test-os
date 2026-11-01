from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from app.api.deps import current_user
from app.core.redis import get_redis
from app.models.dto.compensation import StoredSuggestionOut, SuggestionCreateIn
from app.service.compensation.suggestions import SuggestionStore

router = APIRouter(tags=["compensation"])


@router.post("/compensation/suggestions", response_model=StoredSuggestionOut)
async def create_suggestion(
    body: SuggestionCreateIn,
    _: object = Depends(current_user),
    redis: Redis = Depends(get_redis),
) -> StoredSuggestionOut:
    return await SuggestionStore(redis).create(body)


@router.get("/compensation/suggestions/{suggestion_id}", response_model=StoredSuggestionOut)
async def get_suggestion(
    suggestion_id: str,
    _: object = Depends(current_user),
    redis: Redis = Depends(get_redis),
) -> StoredSuggestionOut:
    return await SuggestionStore(redis).get(suggestion_id)
