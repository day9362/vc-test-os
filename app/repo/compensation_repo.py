from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.models.orm.compensation import CompHistoryOrm


class CompensationRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    def record(self, actor: str, machine_id: str, mode: str, compensation: list, audit_id: str) -> CompHistoryOrm:
        row = CompHistoryOrm(
            id=f"CH-{uuid4().hex[:12]}",
            time=now_ms(),
            actor=actor,
            machine_id=machine_id,
            mode=mode,
            compensation=compensation,
            audit_id=audit_id,
        )
        self.session.add(row)
        return row
