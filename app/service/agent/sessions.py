from dataclasses import dataclass, field
from uuid import uuid4

from app.core.clock import now_ms
from app.core.errors import AppError

MODULES = ("agent.plan", "agent.ops", "agent.analysis")


@dataclass
class AgentMessage:
    id: str
    role: str
    text: str
    blocks: list[dict]
    module: str | None
    tokens: list[int] | None
    time: int


@dataclass
class AgentSession:
    session_id: str
    user_id: str
    module: str
    sdk_session_id: str | None = None
    messages: list[AgentMessage] = field(default_factory=list)
    _seq: int = 0

    def add(self, role: str, text: str, blocks: list[dict] | None = None, tokens: list[int] | None = None) -> AgentMessage:
        self._seq += 1
        message = AgentMessage(
            id=f"{self.session_id}-{self._seq}",
            role=role,
            text=text,
            blocks=blocks or [],
            module=self.module if role == "agent" else None,
            tokens=tokens,
            time=now_ms(),
        )
        self.messages.append(message)
        return message


class AgentStore:
    def __init__(self) -> None:
        self._items: dict[str, AgentSession] = {}

    def create(self, user_id: str, module: str) -> AgentSession:
        if module not in MODULES:
            raise AppError(422, "INVALID_MODULE", "未知的 Agent 模块")
        session = AgentSession(session_id=f"agt-{uuid4().hex[:8]}", user_id=user_id, module=module)
        self._items[session.session_id] = session
        return session

    def get(self, user_id: str, session_id: str) -> AgentSession:
        session = self._items.get(session_id)
        if session is None or session.user_id != user_id:
            raise AppError(404, "NOT_FOUND", "对话不存在")
        return session

    async def send(self, user_id: str, session_id: str, text: str) -> AgentMessage:
        from app.service.agent.runtime import run_turn

        session = self.get(user_id, session_id)
        session.add("user", text)
        turn = await run_turn(session.module, text, session.sdk_session_id)
        if turn.get("sdk_session_id"):
            session.sdk_session_id = turn["sdk_session_id"]
        return session.add("agent", turn.get("text") or "", turn.get("blocks") or [], turn.get("tokens"))


store = AgentStore()
