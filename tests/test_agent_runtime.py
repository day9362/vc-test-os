import unittest
from types import SimpleNamespace

from app.core.config import settings
from app.core.errors import AppError
from app.service.agent.draft import plan_from_reply
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


class DraftParseTests(unittest.TestCase):
    def test_reads_fenced_plan(self) -> None:
        reply = """方案如下：
```json
{"name":"HVP 3.5W 三分钟","start_temp_c":45,"duration_s":180,"sample_period_s":1,"power_w":3.5,"force_g":120,"orientation":90,"overtemp_c":80,"ambient_low_c":23,"ambient_high_c":27,"limits":[{"item":"Temp_T0-T1","low":0,"high":3.4,"unit":"℃","skipped":"false"},{"item":"power_w","low":3.4,"high":3.6,"unit":"W","skipped":false}],"notes":["压紧力按 120 g 填写"]}
```"""
        body, notes = plan_from_reply(reply)
        self.assertEqual(body.name, "HVP 3.5W 三分钟")
        self.assertEqual(body.power_w, 3.5)
        self.assertEqual(body.orientation, 90)
        self.assertFalse(body.limits[0].skipped)
        self.assertEqual(notes, ["压紧力按 120 g 填写"])

    def test_fills_limits_when_model_omits_them(self) -> None:
        body, notes = plan_from_reply('{"name":"快速检查","duration_s":10,"power_w":2.5}')
        self.assertEqual([rule.item for rule in body.limits], ["power_w"])
        self.assertTrue(any("判定项" in note for note in notes))

    def test_rejects_prose_without_json(self) -> None:
        with self.assertRaises(AppError) as caught:
            plan_from_reply("好的，我来写一份方案。")
        self.assertEqual(caught.exception.code, "AGENT_FAILED")


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
