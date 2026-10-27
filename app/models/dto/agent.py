from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


ModuleName = Literal["agent.plan", "agent.ops", "agent.analysis"]


class CreateSessionIn(BaseModel):
    module: ModuleName = "agent.ops"


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    model: str = ""
    batches: list[str] = Field(default_factory=list)


class ToolBlock(BaseModel):
    type: Literal["tool"] = "tool"
    name: str
    args: str = ""
    result: str = ""


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    id: str
    title: str
    columns: list[str]
    rows: list[list[str]]
    more: int = 0


class ChartBlock(BaseModel):
    type: Literal["chart"] = "chart"
    id: str
    title: str
    option: dict[str, Any]


class ChoiceOption(BaseModel):
    label: str
    text: str


class ChoicesBlock(BaseModel):
    type: Literal["choices"] = "choices"
    id: str
    options: list[ChoiceOption]
    chosen: int | None = None


class ActionBlock(BaseModel):
    type: Literal["action"] = "action"
    id: str
    name: str
    desc: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "done", "rejected"] = "pending"
    result: str = ""
    risk: Literal["low", "high"] = "low"


Block = Annotated[ToolBlock | TableBlock | ChartBlock | ChoicesBlock | ActionBlock, Field(discriminator="type")]


class ActionDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]


class ChoiceIn(BaseModel):
    index: int = Field(ge=0, le=3)


class AgentMessageOut(BaseModel):
    id: str
    role: Literal["user", "agent"]
    text: str
    blocks: list[Block]
    module: str | None = None
    tokens: list[int] | None = None
    time: int


class SessionSummaryOut(BaseModel):
    session_id: str
    module: str
    title: str
    updated_at: int


class SessionOut(BaseModel):
    session_id: str
    module: str
    title: str
    messages: list[AgentMessageOut]


def session_out(session, messages: list) -> SessionOut:
    return SessionOut(
        session_id=session.session_id,
        module=session.module,
        title=session.title,
        messages=[AgentMessageOut.model_validate(item, from_attributes=True) for item in messages],
    )
