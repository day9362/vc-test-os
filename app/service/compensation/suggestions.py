import json
import secrets

from redis.asyncio import Redis

from app.core.errors import AppError
from app.models.dto.compensation import StoredSuggestionOut, SuggestionCreateIn

_MEMORY: dict[str, str] = {}


class SuggestionStore:
    def __init__(self, redis: Redis | None = None):
        self.redis = redis

    async def create(self, body: SuggestionCreateIn) -> StoredSuggestionOut:
        suggestion_id = "sg_" + secrets.token_hex(8)
        record = StoredSuggestionOut(suggestion_id=suggestion_id, **body.model_dump())
        raw = record.model_dump_json()
        _MEMORY[suggestion_id] = raw
        if self.redis is not None:
            try:
                await self.redis.set(f"comp:suggest:{suggestion_id}", raw, ex=86400)
            except Exception:
                pass
        return record

    async def get(self, suggestion_id: str) -> StoredSuggestionOut:
        raw = _MEMORY.get(suggestion_id)
        if raw is None and self.redis is not None:
            try:
                raw = await self.redis.get(f"comp:suggest:{suggestion_id}")
            except Exception:
                raw = None
        if not raw:
            raise AppError(404, "NOT_FOUND", "没有这条补偿建议，或建议已经过期")
        return StoredSuggestionOut.model_validate(json.loads(raw))
