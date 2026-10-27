from typing import Literal

from pydantic import BaseModel, Field


ModuleName = Literal["agent.plan", "agent.ops", "agent.analysis"]


class CreateSessionIn(BaseModel):
    module: ModuleName = "agent.ops"


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ToolBlock(BaseModel):
    type: Literal["tool"] = "tool"
    name: str
    args: str = ""
    result: str = ""


class AgentMessageOut(BaseModel):
    id: str
    role: Literal["user", "agent"]
    text: str
    blocks: list[ToolBlock]
    module: str | None = None
    tokens: list[int] | None = None
    time: int


class SessionOut(BaseModel):
    session_id: str
    module: str
    messages: list[AgentMessageOut]


def session_out(session) -> SessionOut:
    return SessionOut(
        session_id=session.session_id,
        module=session.module,
        messages=[AgentMessageOut.model_validate(item, from_attributes=True) for item in session.messages],
    )
