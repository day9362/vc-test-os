import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from app.core.config import settings
from app.models.dto.production import ProductionIn

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT / ".agent" / "workspace"
CONFIG = ROOT / ".agent" / "claude-config"
TEST_TOOL = "mcp__vapor-chamber__test"


class McpCallError(RuntimeError):
    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.detail = detail


def start_args(body: ProductionIn) -> dict:
    return {
        "action": "production",
        "enable": True,
        "machine_ids": body.machine_ids,
        "plan_id": body.plan_id,
        "plan_version": body.plan_version,
        "batch_id": body.batch_id,
        "serial_numbers": body.serial_numbers,
        "auto_recover": body.auto_recover,
        "max_count": body.max_count,
    }


def stop_args(batch_id: str) -> dict:
    return {"action": "production", "enable": False, "batch_id": batch_id}


async def start_on_device(body: ProductionIn) -> dict:
    if settings.anthropic_api_key and settings.anthropic_base_url:
        try:
            return await call_test(start_args(body))
        except McpCallError:
            pass
    from app.service.production.cluster import post_production
    payload = {key: value for key, value in start_args(body).items() if key not in {"action", "enable"} and value is not None}
    return await post_production("/fleet/production/start", payload) or {}


async def stop_on_device(batch_id: str) -> dict:
    if settings.anthropic_api_key and settings.anthropic_base_url:
        try:
            return await call_test(stop_args(batch_id))
        except McpCallError:
            pass
    from app.service.production.cluster import post_production
    return await post_production("/fleet/production/stop", {"batch_id": batch_id}) or {}


async def call_test(arguments: dict) -> dict:
    """让 Claude Agent SDK 只调用 vapor-chamber 的 test 工具。

    Windows 上 API 进程常用 Selector 循环，这个循环不能拉起 Claude CLI 子进程，
    所以改放到线程里的 Proactor 循环执行。
    """
    loop = asyncio.get_running_loop()
    if sys.platform == "win32" and not isinstance(loop, asyncio.ProactorEventLoop):
        return await asyncio.to_thread(_run_on_proactor, arguments)
    return await _call_test(arguments)


def _run_on_proactor(arguments: dict) -> dict:
    proactor = asyncio.ProactorEventLoop()
    try:
        asyncio.set_event_loop(proactor)
        return proactor.run_until_complete(_call_test(arguments))
    finally:
        proactor.run_until_complete(proactor.shutdown_asyncgens())
        proactor.close()
        asyncio.set_event_loop(None)


async def _call_test(arguments: dict) -> dict:
    if not settings.anthropic_api_key or not settings.anthropic_base_url:
        raise McpCallError("没有配置模型地址或密钥")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    CONFIG.mkdir(parents=True, exist_ok=True)
    options = ClaudeAgentOptions(
        cwd=str(WORKSPACE),
        model=settings.anthropic_model,
        system_prompt="你只调用已接入的 MCP 工具 test，参数必须与用户给出的 JSON 完全一致。不要调用其它工具，不要改参数。",
        tools=[],
        allowed_tools=[TEST_TOOL],
        permission_mode="acceptEdits",
        mcp_servers={"vapor-chamber": {"type": "http", "url": settings.mcp_url}},
        strict_mcp_config=True,
        setting_sources=[],
        max_turns=4,
        env=_env(),
    )
    prompt = "调用 test，参数 JSON 如下：\n" + json.dumps(arguments, ensure_ascii=False)
    messages: list[Any] = []
    client = ClaudeSDKClient(options=options)
    await client.connect()
    try:
        await client.query(prompt)
        async for message in client.receive_response():
            messages.append(message)
    finally:
        await client.disconnect()
    names = _tool_names(messages)
    if TEST_TOOL not in names and "test" not in names:
        raise McpCallError("模型没有调用 test 工具", {"tools": names, "text": _text(messages)})
    payload = _tool_json(messages)
    if payload is None:
        raise McpCallError("test 工具没有返回结果", {"text": _text(messages)})
    if payload.get("ok") is False:
        raise McpCallError(str(payload.get("summary") or "设备层拒绝了这次下发"), payload)
    data = payload.get("data")
    return data if isinstance(data, dict) else {"raw": data, "summary": payload.get("summary")}


def _env() -> dict[str, str]:
    env = {
        "ANTHROPIC_BASE_URL": settings.anthropic_base_url.rstrip("/"),
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
        "ANTHROPIC_AUTH_TOKEN": settings.anthropic_api_key,
        "CLAUDE_CONFIG_DIR": str(CONFIG),
        "CLAUDE_AGENT_SDK_CLIENT_APP": "vc-test-os",
    }
    if os.environ.get("PATH"):
        env["PATH"] = os.environ["PATH"]
    return env


def _tool_names(messages: list[Any]) -> list[str]:
    names: list[str] = []
    for message in messages:
        if not isinstance(message, AssistantMessage) or not isinstance(message.content, list):
            continue
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                names.append(block.name)
    return names


def _tool_json(messages: list[Any]) -> dict | None:
    for message in messages:
        content = getattr(message, "content", None)
        blocks = content if isinstance(content, list) else []
        for block in blocks:
            if isinstance(block, ToolResultBlock):
                parsed = parse_tool_payload(block.content)
                if parsed is not None:
                    return parsed
            if isinstance(block, TextBlock):
                parsed = parse_tool_payload(block.text)
                if isinstance(parsed, dict) and "ok" in parsed:
                    return parsed
        if isinstance(message, UserMessage):
            parsed = parse_tool_payload(content if isinstance(content, str) else None)
            if isinstance(parsed, dict) and "ok" in parsed:
                return parsed
    return None


def parse_tool_payload(content: Any) -> dict | None:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parsed = parse_tool_payload(item.get("text"))
                if parsed is not None:
                    return parsed
        return None
    if not isinstance(content, str):
        return None
    text = content.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _text(messages: list[Any]) -> str:
    parts: list[str] = []
    for message in messages:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, TextBlock) and block.text:
                    parts.append(block.text)
    return "\n".join(parts)[:1000]
