from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.models.orm.alarm import AuditOrm


class AuditRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    def record(self, actor: str, action: str, machine_id: str, request: dict, result: dict) -> str:
        audit_id = f"AUD-{uuid4().hex[:12]}"
        self.session.add(AuditOrm(
            audit_id=audit_id,
            time=now_ms(),
            actor=actor,
            action=action,
            machine_id=machine_id,
            request=request,
            result=result,
        ))
        return audit_id
