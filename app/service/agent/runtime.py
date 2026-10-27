import asyncio
import os
import queue
import sys
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.errors import AppError
from app.service.agent.prompts import MCP_TOOLS, system_prompt
from app.service.agent.transcript import TurnBuilder, turn_from_messages

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT / ".agent" / "workspace"
CONFIG = ROOT / ".agent" / "claude-config"


def model_env() -> dict[str, str]:
    base = settings.anthropic_base_url.rstrip("/")
    env = {
        "ANTHROPIC_BASE_URL": base,
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
        "ANTHROPIC_AUTH_TOKEN": settings.anthropic_api_key,
        "CLAUDE_CONFIG_DIR": str(CONFIG),
        "CLAUDE_AGENT_SDK_CLIENT_APP": "vc-test-os",
    }
    if settings.anthropic_model:
        env["ANTHROPIC_MODEL"] = settings.anthropic_model
    if os.environ.get("PATH"):
        env["PATH"] = os.environ["PATH"]
    return env


async def iter_turn(
    module: str,
    text: str,
    sdk_session_id: str | None,
    *,
    system: str | None = None,
    allowed_tools: list[str] | None = None,
    max_turns: int = 12,
) -> AsyncIterator[dict]:
    if not settings.anthropic_base_url or not settings.anthropic_api_key:
        raise AppError(503, "MODEL_NOT_CONFIGURED", "没有配置第三方模型地址或密钥")
    loop = asyncio.get_running_loop()
    if sys.platform == "win32" and not isinstance(loop, asyncio.ProactorEventLoop):
        async for event in _bridge(module, text, sdk_session_id, system, allowed_tools, max_turns):
            yield event
        return
    async for event in _iter_turn(module, text, sdk_session_id, system, allowed_tools, max_turns):
        yield event


async def _bridge(
    module: str,
    text: str,
    sdk_session_id: str | None,
    system: str | None,
    allowed_tools: list[str] | None,
    max_turns: int,
) -> AsyncIterator[dict]:
    events: queue.Queue = queue.Queue()

    def worker() -> None:
        proactor = asyncio.ProactorEventLoop()
        try:
            asyncio.set_event_loop(proactor)

            async def forward() -> None:
                async for event in _iter_turn(module, text, sdk_session_id, system, allowed_tools, max_turns):
                    events.put(event)

            proactor.run_until_complete(forward())
        except Exception:
            events.put({"type": "error", "message": "Agent 没有完成这次对话"})
        finally:
            events.put(None)
            try:
                proactor.run_until_complete(proactor.shutdown_asyncgens())
            finally:
                proactor.close()
                asyncio.set_event_loop(None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        event = await asyncio.to_thread(events.get)
        if event is None:
            break
        yield event


async def run_turn(
    module: str,
    text: str,
    sdk_session_id: str | None,
    *,
    system: str | None = None,
    allowed_tools: list[str] | None = None,
    max_turns: int = 12,
) -> dict:
    if not settings.anthropic_base_url or not settings.anthropic_api_key:
        raise AppError(503, "MODEL_NOT_CONFIGURED", "没有配置第三方模型地址或密钥")
    loop = asyncio.get_running_loop()
    if sys.platform == "win32" and not isinstance(loop, asyncio.ProactorEventLoop):
        return await asyncio.to_thread(_run_on_proactor, module, text, sdk_session_id, system, allowed_tools, max_turns)
    return await _run_turn(module, text, sdk_session_id, system, allowed_tools, max_turns)


def _run_on_proactor(
    module: str,
    text: str,
    sdk_session_id: str | None,
    system: str | None,
    allowed_tools: list[str] | None,
    max_turns: int,
) -> dict:
    proactor = asyncio.ProactorEventLoop()
    try:
        asyncio.set_event_loop(proactor)
        return proactor.run_until_complete(_run_turn(module, text, sdk_session_id, system, allowed_tools, max_turns))
    finally:
        proactor.run_until_complete(proactor.shutdown_asyncgens())
        proactor.close()
        asyncio.set_event_loop(None)


async def _run_turn(
    module: str,
    text: str,
    sdk_session_id: str | None,
    system: str | None = None,
    allowed_tools: list[str] | None = None,
    max_turns: int = 12,
) -> dict:
    try:
        from claude_agent_sdk import ClaudeSDKClient
    except ImportError as exc:
        raise AppError(503, "AGENT_SDK_MISSING", "没有安装 Claude Agent SDK") from exc
    options = _options(module, sdk_session_id, system, allowed_tools, max_turns, partial=False)
    messages: list[Any] = []
    client = ClaudeSDKClient(options=options)
    await client.connect()
    try:
        await client.query(text)
        async for message in client.receive_response():
            messages.append(message)
    except Exception as exc:
        raise AppError(502, "AGENT_FAILED", "Agent 没有完成这次对话", {"reason": str(exc)}) from exc
    finally:
        await client.disconnect()
    turn = turn_from_messages(messages)
    if turn.pop("failed"):
        raise AppError(502, "AGENT_FAILED", turn["text"] or "Agent 没有完成这次对话")
    return turn


async def _iter_turn(
    module: str,
    text: str,
    sdk_session_id: str | None,
    system: str | None = None,
    allowed_tools: list[str] | None = None,
    max_turns: int = 12,
) -> AsyncIterator[dict]:
    try:
        from claude_agent_sdk import ClaudeSDKClient
    except ImportError:
        yield {"type": "error", "message": "没有安装 Claude Agent SDK"}
        return
    options = _options(module, sdk_session_id, system, allowed_tools, max_turns, partial=True)
    builder = TurnBuilder()
    client = ClaudeSDKClient(options=options)
    try:
        await client.connect()
        try:
            await client.query(text)
            async for message in client.receive_response():
                for event in builder.feed(message):
                    yield event
        finally:
            await client.disconnect()
    except Exception:
        if not builder.hit_turn_limit():
            yield {"type": "error", "message": "Agent 没有完成这次对话", "turn": builder.finish()}
            return
    if builder.hit_turn_limit():
        async for event in _conclude(module, builder):
            yield event
    turn = builder.finish()
    if turn.pop("failed"):
        yield {"type": "error", "message": turn["text"] or "Agent 没有完成这次对话"}
        return
    yield {"type": "done", **turn}


_CONCLUDE = "根据这次对话里已经返回的记录，用中文回答用户原来的问题。不要调用工具。先写结论，只使用已经出现的批次、合格数和失败项。没查到的写还没查到，不要编造。"


async def _conclude(module: str, builder: TurnBuilder) -> AsyncIterator[dict]:
    session_id = builder.sdk_session_id
    builder.stopped_early = True
    builder.result_text = ""
    builder.errors = [item for item in builder.errors if "maximum number of turns" not in item.lower()]
    builder.failed = False
    if not session_id:
        return
    from claude_agent_sdk import ClaudeSDKClient

    client = ClaudeSDKClient(_options(module, session_id, _CONCLUDE, [], 2, partial=True))
    try:
        await client.connect()
        try:
            await client.query("根据已经查到的记录写出结论。不要再调用工具。")
            async for message in client.receive_response():
                for event in builder.feed(message):
                    yield event
        finally:
            await client.disconnect()
    except Exception:
        return


def _options(
    module: str,
    sdk_session_id: str | None,
    system: str | None,
    allowed_tools: list[str] | None,
    max_turns: int,
    *,
    partial: bool,
):
    from claude_agent_sdk import ClaudeAgentOptions

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    CONFIG.mkdir(parents=True, exist_ok=True)
    return ClaudeAgentOptions(
        cwd=str(WORKSPACE),
        model=settings.anthropic_model or None,
        system_prompt=system or system_prompt(module),
        tools=[],
        allowed_tools=MCP_TOOLS if allowed_tools is None else allowed_tools,
        disallowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch"],
        permission_mode="acceptEdits",
        mcp_servers={} if allowed_tools == [] else {"vapor-chamber": {"type": "http", "url": settings.mcp_url}},
        strict_mcp_config=True,
        setting_sources=[],
        max_turns=max_turns,
        resume=sdk_session_id,
        include_partial_messages=partial,
        env=model_env(),
    )
