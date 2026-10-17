from pydantic import BaseModel


class SearchHitOut(BaseModel):
    id: str
    text: str


class SearchOut(BaseModel):
    machines: list[SearchHitOut]
    batches: list[SearchHitOut]
    plans: list[SearchHitOut]
    runs: list[SearchHitOut]
