from typing import Any

from pydantic import BaseModel, Field


class SubscribeIn(BaseModel):
    op: str
    topics: list[str] = Field(default_factory=list)


class Envelope(BaseModel):
    topic: str
    ts: int
    data: Any = None
