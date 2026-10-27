import json
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.clock import now_ms
from app.core.config import settings
from app.core.errors import AppError
from app.models.orm.agent_session import AgentMessageOrm, AgentSessionOrm

MODULES = ("agent.plan", "agent.ops", "agent.analysis")
_IN_FLIGHT: set[str] = set()


def session_title(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:24] or "新对话"


class AgentSessionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str, module: str) -> AgentSessionOrm:
        if module not in MODULES:
            raise AppError(422, "INVALID_MODULE", "未知的 Agent 模块")
        stamp = now_ms()
        row = AgentSessionOrm(
            session_id=f"agt-{uuid4().hex[:8]}",
            user_id=user_id,
            module=module,
            title="新对话",
            created_at=stamp,
            updated_at=stamp,
        )
        self.session.add(row)
        await self.session.commit()
        return row

    async def list_for(self, user_id: str, module: str) -> list[AgentSessionOrm]:
        if module not in MODULES:
            raise AppError(422, "INVALID_MODULE", "未知的 Agent 模块")
        rows = await self.session.scalars(
            select(AgentSessionOrm)
            .where(AgentSessionOrm.user_id == user_id, AgentSessionOrm.module == module)
            .order_by(AgentSessionOrm.updated_at.desc())
        )
        return list(rows)

    async def delete(self, user_id: str, session_id: str) -> None:
        row = await self._owned(user_id, session_id)
        await self.session.execute(delete(AgentMessageOrm).where(AgentMessageOrm.session_id == row.session_id))
        await self.session.delete(row)
        await self.session.commit()

    async def get(self, user_id: str, session_id: str) -> tuple[AgentSessionOrm, list[AgentMessageOrm]]:
        row = await self._owned(user_id, session_id)
        messages = await self.session.scalars(
            select(AgentMessageOrm).where(AgentMessageOrm.session_id == session_id).order_by(AgentMessageOrm.seq)
        )
        return row, list(messages)

    async def prepare(self, user_id: str, session_id: str, text: str) -> tuple[str, str | None]:
        row = await self._owned(user_id, session_id)
        if row.title == "新对话":
            row.title = session_title(text)
        module = row.module
        sdk_session_id = row.sdk_session_id
        await self._append(row, "user", text, None, None)
        await self.session.commit()
        return module, sdk_session_id

    async def save_reply(self, user_id: str, session_id: str, turn: dict, *, actor: str, started_ms: int, ok: bool = True) -> AgentMessageOrm:
        row = await self._owned(user_id, session_id)
        if turn.get("sdk_session_id"):
            row.sdk_session_id = turn["sdk_session_id"]
        reply = await self._append(row, "agent", turn.get("text") or "", turn.get("blocks") or [], turn.get("tokens"))
        await self._record_usage(row.module, actor, turn, started_ms, session_id, ok)
        await self.session.commit()
        return reply

    async def record_usage(self, user_id: str, session_id: str, turn: dict | None, *, actor: str, started_ms: int, ok: bool) -> None:
        row = await self._owned(user_id, session_id)
        await self._record_usage(row.module, actor, turn, started_ms, session_id, ok)
        await self.session.commit()

    async def decide(self, user_id: str, session_id: str, action_id: str, decision: str) -> dict:
        from app.service.agent.actions import call_confirmed

        if action_id in _IN_FLIGHT:
            raise AppError(409, "IN_PROGRESS", "这个操作正在执行")
        row = await self._owned(user_id, session_id)
        message, blocks, action = await self._action(session_id, action_id)
        if action.get("status") != "pending":
            raise AppError(409, "ALREADY_DECIDED", "这个操作已经处理过")
        if decision == "reject":
            action["status"] = "rejected"
            action["result"] = "已拒绝"
            row.updated_at = now_ms()
            self._store_blocks(message, blocks)
            await self.session.commit()
            return action
        _IN_FLIGHT.add(action_id)
        try:
            outcome = await call_confirmed(str(action.get("name") or ""), action.get("arguments") or {})
        except AppError:
            raise
        finally:
            _IN_FLIGHT.discard(action_id)
        if outcome.get("ok") is False:
            action["result"] = str(outcome.get("summary") or outcome.get("detail") or "没有执行")[:200]
            row.updated_at = now_ms()
            self._store_blocks(message, blocks)
            await self.session.commit()
            raise AppError(409, "NOT_EXECUTED", action["result"])
        action["status"] = "done"
        action["result"] = str(outcome.get("summary") or "已执行")[:200]
        row.updated_at = now_ms()
        self._store_blocks(message, blocks)
        await self.session.commit()
        return action

    async def choose(self, user_id: str, session_id: str, choice_id: str, index: int) -> dict:
        row = await self._owned(user_id, session_id)
        message, blocks, choice = await self._block(session_id, choice_id, "choices")
        if choice.get("chosen") is not None:
            raise AppError(409, "ALREADY_CHOSEN", "这个选项已经选过")
        options = choice.get("options") or []
        if index >= len(options):
            raise AppError(422, "BAD_CHOICE", "没有这个选项")
        choice["chosen"] = index
        row.updated_at = now_ms()
        self._store_blocks(message, blocks)
        await self.session.commit()
        return choice

    async def send(self, user_id: str, session_id: str, text: str, *, actor: str, model: str = "", batches: list[str] | None = None) -> AgentMessageOrm:
        from app.service.agent.runtime import run_turn
        from app.service.agent.scope import with_scope

        started = now_ms()
        module, sdk_session_id = await self.prepare(user_id, session_id, text)
        turn = await run_turn(module, with_scope(text, model, batches or []), sdk_session_id)
        return await self.save_reply(user_id, session_id, turn, actor=actor, started_ms=started)

    async def _record_usage(self, module: str, actor: str, turn: dict | None, started_ms: int, session_id: str, ok: bool) -> None:
        from app.service.ai.usage import UsageService

        tokens = (turn or {}).get("tokens") or [0, 0]
        await UsageService(self.session).record(
            module=module,
            user=actor or "用户",
            model=settings.anthropic_model or "agent",
            input_tokens=int(tokens[0] or 0),
            output_tokens=int(tokens[1] or 0) if len(tokens) > 1 else 0,
            latency_ms=max(now_ms() - started_ms, 1),
            ok=ok,
            ref={"session_id": session_id},
        )

    async def _action(self, session_id: str, action_id: str) -> tuple[AgentMessageOrm, list, dict]:
        return await self._block(session_id, action_id, "action", "这个操作不在这场对话里")

    async def _block(self, session_id: str, block_id: str, kind: str, missing: str = "这个选项不在这场对话里") -> tuple[AgentMessageOrm, list, dict]:
        messages = await self.session.scalars(
            select(AgentMessageOrm).where(AgentMessageOrm.session_id == session_id).order_by(AgentMessageOrm.seq)
        )
        for message in messages:
            blocks = json.loads(json.dumps(message.blocks or []))
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == kind and block.get("id") == block_id:
                    return message, blocks, block
        raise AppError(404, "NOT_FOUND", missing)

    def _store_blocks(self, message: AgentMessageOrm, blocks: list) -> None:
        message.blocks = blocks
        flag_modified(message, "blocks")

    async def _owned(self, user_id: str, session_id: str) -> AgentSessionOrm:
        row = await self.session.get(AgentSessionOrm, session_id)
        if row is None or row.user_id != user_id:
            raise AppError(404, "NOT_FOUND", "对话不存在")
        return row

    async def _append(self, row: AgentSessionOrm, role: str, text: str, blocks: list | None, tokens: list | None) -> AgentMessageOrm:
        seq = await self.session.scalar(select(func.coalesce(func.max(AgentMessageOrm.seq), 0)).where(AgentMessageOrm.session_id == row.session_id))
        message = AgentMessageOrm(
            id=f"{row.session_id}-{int(seq or 0) + 1}",
            session_id=row.session_id,
            seq=int(seq or 0) + 1,
            role=role,
            text=text,
            blocks=blocks or [],
            module=row.module if role == "agent" else None,
            tokens=tokens,
            time=now_ms(),
        )
        row.updated_at = message.time
        self.session.add(message)
        return message
