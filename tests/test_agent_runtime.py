import unittest
from types import SimpleNamespace

from app.core.config import settings
from app.core.errors import AppError
from app.service.agent.runtime import model_env, run_turn
from app.service.agent.sessions import AgentStore
from app.service.agent.transcript import turn_from_messages


class TranscriptTests(unittest.TestCase):
    def test_pairs_tool_call_with_result(self) -> None:
        assistant = _named("AssistantMessage", content=[
            _named("TextBlock", text="先看机台。"),
            _named("ToolUseBlock", id="t1", name="mcp__vapor-chamber__plan", input={"action": "dispatch", "machine_id": "M01", "plan_id": "PLAN-1"}),
        ])
        user = _named("UserMessage", content=[
            _named("ToolResultBlock", tool_use_id="t1", content=[{"type": "text", "text": '{"ok": true, "summary": "已下发"}'}]),
        ])
        result = _named("ResultMessage", result="方案已经下发到 M01。", usage={"input_tokens": 120, "output_tokens": 40}, session_id="sdk-1", is_error=False, errors=None)
        turn = turn_from_messages([assistant, user, result])
        self.assertEqual(turn["text"], "方案已经下发到 M01。")
        self.assertEqual(turn["blocks"][0]["name"], "mcp__vapor-chamber__plan")
        self.assertIn("M01", turn["blocks"][0]["args"])
        self.assertIn("已下发", turn["blocks"][0]["result"])
        self.assertEqual(turn["tokens"], [120, 40])
        self.assertEqual(turn["sdk_session_id"], "sdk-1")


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_unknown_module(self) -> None:
        with self.assertRaises(AppError) as caught:
            AgentStore().create("u1", "agent.other")
        self.assertEqual(caught.exception.status, 422)

    async def test_hides_another_users_session(self) -> None:
        store = AgentStore()
        session = store.create("u1", "agent.ops")
        with self.assertRaises(AppError) as caught:
            store.get("u2", session.session_id)
        self.assertEqual(caught.exception.status, 404)

    async def test_missing_model_config_stops_before_sdk(self) -> None:
        previous = settings.anthropic_api_key, settings.anthropic_base_url
        settings.anthropic_api_key = ""
        settings.anthropic_base_url = ""
        try:
            with self.assertRaises(AppError) as caught:
                await run_turn("agent.ops", "停止连续生产", None)
        finally:
            settings.anthropic_api_key, settings.anthropic_base_url = previous
        self.assertEqual(caught.exception.code, "MODEL_NOT_CONFIGURED")


class EnvTests(unittest.TestCase):
    def test_third_party_base_url_is_passed_to_sdk(self) -> None:
        previous = settings.anthropic_base_url, settings.anthropic_api_key, settings.anthropic_model
        settings.anthropic_base_url = "https://gateway.example/anthropic/"
        settings.anthropic_api_key = "sk-test"
        settings.anthropic_model = "deepseek-flash"
        try:
            env = model_env()
        finally:
            settings.anthropic_base_url, settings.anthropic_api_key, settings.anthropic_model = previous
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://gateway.example/anthropic")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "sk-test")
        self.assertEqual(env["ANTHROPIC_MODEL"], "deepseek-flash")


def _named(kind: str, **kwargs):
    return type(kind, (SimpleNamespace,), {})(**kwargs)
