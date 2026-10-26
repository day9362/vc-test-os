import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.errors import AppError
from app.service.agent.prompts import MCP_TOOLS, system_prompt
from app.service.agent.transcript import turn_from_messages

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


async def run_turn(module: str, text: str, sdk_session_id: str | None) -> dict:
    if not settings.anthropic_base_url or not settings.anthropic_api_key:
        raise AppError(503, "MODEL_NOT_CONFIGURED", "没有配置第三方模型地址或密钥")
    loop = asyncio.get_running_loop()
    if sys.platform == "win32" and not isinstance(loop, asyncio.ProactorEventLoop):
        return await asyncio.to_thread(_run_on_proactor, module, text, sdk_session_id)
    return await _run_turn(module, text, sdk_session_id)


def _run_on_proactor(module: str, text: str, sdk_session_id: str | None) -> dict:
    proactor = asyncio.ProactorEventLoop()
    try:
        asyncio.set_event_loop(proactor)
        return proactor.run_until_complete(_run_turn(module, text, sdk_session_id))
    finally:
        proactor.run_until_complete(proactor.shutdown_asyncgens())
        proactor.close()
        asyncio.set_event_loop(None)


async def _run_turn(module: str, text: str, sdk_session_id: str | None) -> dict:
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
    except ImportError as exc:
        raise AppError(503, "AGENT_SDK_MISSING", "没有安装 Claude Agent SDK") from exc
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    CONFIG.mkdir(parents=True, exist_ok=True)
    options = ClaudeAgentOptions(
        cwd=str(WORKSPACE),
        model=settings.anthropic_model or None,
        system_prompt=system_prompt(module),
        tools=[],
        allowed_tools=MCP_TOOLS,
        disallowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch"],
        permission_mode="acceptEdits",
        mcp_servers={"vapor-chamber": {"type": "http", "url": settings.mcp_url}},
        strict_mcp_config=True,
        setting_sources=[],
        max_turns=12,
        resume=sdk_session_id,
        env=model_env(),
    )
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
