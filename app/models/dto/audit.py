from pydantic import BaseModel


class AuditItemOut(BaseModel):
    audit_id: str
    time: int
    actor: str
    action: str
    machine_id: str
    request: dict
    result: dict


class AuditPageOut(BaseModel):
    items: list[AuditItemOut]
    next_cursor: str | None
