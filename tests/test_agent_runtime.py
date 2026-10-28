import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.config import settings
from app.core.errors import AppError
from app.service.agent.draft import plan_from_reply
from app.service.agent.prompts import MCP_TOOLS
from app.service.agent.runtime import model_env, run_turn
from app.service.agent.scope import with_scope
from app.service.agent.sessions import AgentSessionService, session_title
from app.service.agent.actions import confirmation_card, strip_model_confirmation
from app.service.agent.cards import extract_choices, present_cards
from app.service.agent.transcript import TurnBuilder, turn_from_messages


class TranscriptTests(unittest.TestCase):
    def test_pairs_tool_call_with_result(self) -> None:
        assistant = _named("AssistantMessage", content=[
            _named("TextBlock", text="先看机台。"),
            _named("ToolUseBlock", id="t1", name="mcp__vapor-chamber__cluster_plan", input={"action": "dispatch", "machine_id": "M01", "plan_id": "PLAN-1"}),
        ])
        user = _named("UserMessage", content=[
            _named("ToolResultBlock", tool_use_id="t1", content=[{"type": "text", "text": '{"ok": true, "summary": "已下发"}'}]),
        ])
        result = _named("ResultMessage", result="方案已经下发到 M01。", usage={"input_tokens": 120, "output_tokens": 40}, session_id="sdk-1", is_error=False, errors=None)
        turn = turn_from_messages([assistant, user, result])
        self.assertEqual(turn["text"], "方案已经下发到 M01。")
        self.assertEqual(turn["blocks"][0]["name"], "mcp__vapor-chamber__cluster_plan")
        self.assertIn("M01", turn["blocks"][0]["args"])
        self.assertIn("已下发", turn["blocks"][0]["result"])
        self.assertEqual(turn["tokens"], [120, 40])
        self.assertEqual(turn["sdk_session_id"], "sdk-1")

    def test_streams_text_and_tools_before_the_result(self) -> None:
        builder = TurnBuilder()
        opened = builder.feed(_named("StreamEvent", event={
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "t1", "name": "mcp__vapor-chamber__cluster_plan", "input": {}},
        }))
        deltas = []
        deltas += builder.feed(_named("StreamEvent", event={"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "先看"}}))
        deltas += builder.feed(_named("StreamEvent", event={"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "机台。"}}))
        deltas += builder.feed(_named("StreamEvent", event={"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"machine_id":"M01"}'}}))
        stopped = builder.feed(_named("StreamEvent", event={"type": "content_block_stop", "index": 1}))
        self.assertEqual(opened[0]["name"], "mcp__vapor-chamber__cluster_plan")
        self.assertEqual("".join(item["text"] for item in deltas if item["type"] == "text"), "先看机台。")
        self.assertIn("M01", stopped[0]["args"])
        builder.feed(_named("AssistantMessage", content=[
            _named("TextBlock", text="先看机台。"),
            _named("ToolUseBlock", id="t1", name="mcp__vapor-chamber__cluster_plan", input={"machine_id": "M01"}),
        ]))
        result = _named("ResultMessage", result="先看机台。", usage={"input_tokens": 3, "output_tokens": 2}, session_id="sdk-1", is_error=False, errors=None)
        builder.feed(result)
        turn = builder.finish()
        self.assertEqual(turn["text"], "先看机台。")
        self.assertEqual(len(turn["blocks"]), 1)

    def test_turn_limit_keeps_a_later_answer(self) -> None:
        builder = TurnBuilder()
        builder.feed(_named(
            "ResultMessage",
            result="Reached maximum number of turns (12)",
            usage=None,
            session_id="sdk-1",
            is_error=True,
            errors=["Reached maximum number of turns (12)"],
        ))
        self.assertTrue(builder.hit_turn_limit())
        self.assertEqual(builder.finish()["text"], "工具调用已经用完，结论还没有写出来。")
        builder.stopped_early = True
        builder.result_text = ""
        builder.errors = []
        builder.failed = False
        builder.feed(_named("AssistantMessage", content=[_named("TextBlock", text="三批里 B-tb172-347862aa 有一块 Temp_T0-T1 不合格。")]))
        builder.feed(_named("ResultMessage", result="三批里 B-tb172-347862aa 有一块 Temp_T0-T1 不合格。", usage=None, session_id="sdk-1", is_error=False, errors=None))
        self.assertEqual(builder.finish()["text"], "三批里 B-tb172-347862aa 有一块 Temp_T0-T1 不合格。")

    def test_unconfirmed_write_becomes_a_pending_action(self) -> None:
        refused = json.dumps({
            "ok": False,
            "summary": "还没有得到用户对这一次操作的同意。",
            "detail": "还不能执行。请先向用户说明：把 M08 的仿真倍率改为 2。等用户明确同意这一次之后，再带 human_confirmed=true 调用。",
        }, ensure_ascii=False)
        assistant = _named("AssistantMessage", content=[
            _named("ToolUseBlock", id="t1", name="mcp__vapor-chamber__cluster_control", input={
                "action": "speed",
                "machine_ids": ["M08"],
                "speed": 2,
                "human_confirmed": False,
            }),
        ])
        user = _named("UserMessage", content=[
            _named("ToolResultBlock", tool_use_id="t1", content=[{"type": "text", "text": refused}]),
        ])
        turn = turn_from_messages([assistant, user])
        self.assertEqual(turn["blocks"][0]["type"], "tool")
        self.assertNotIn("call", turn["blocks"][0])
        action = turn["blocks"][1]
        self.assertEqual(action["type"], "action")
        self.assertEqual(action["name"], "cluster_control")
        self.assertEqual(action["status"], "pending")
        self.assertEqual(action["desc"], "把 M08 的仿真倍率改为 2")
        self.assertEqual(action["arguments"], {"action": "speed", "machine_ids": ["M08"], "speed": 2})
        self.assertEqual(action["risk"], "low")
        self.assertNotIn("human_confirmed", action["arguments"])

    def test_model_cannot_mark_a_write_as_already_confirmed(self) -> None:
        refused = '{"ok": false, "summary": "还没有得到用户对这一次操作的同意。", "detail": "请先向用户说明：给 M05 关机。"}'
        self.assertIsNone(confirmation_card("cluster_line", {"action": "overview"}, refused))
        self.assertIsNone(confirmation_card("cluster_plan", {"action": "dispatch"}, refused))
        forced = confirmation_card(
            "cluster_control",
            {"action": "power", "machine_id": "M05", "power_state": "off", "human_confirmed": True},
            refused,
        )
        self.assertIsNotNone(forced)
        assert forced is not None
        self.assertEqual(forced["status"], "pending")
        self.assertEqual(forced["arguments"], {"action": "power", "machine_id": "M05", "power_state": "off"})
        power = confirmation_card(
            "cluster_control",
            {"action": "power", "machine_id": "M05", "power_state": "off"},
            refused,
        )
        self.assertIsNotNone(power)
        assert power is not None
        self.assertEqual(power["risk"], "high")
        self.assertEqual(power["desc"], "给 M05 关机")

    def test_pre_tool_hook_clears_model_confirmation(self) -> None:
        cleared = asyncio.run(strip_model_confirmation({
            "tool_name": "mcp__vapor-chamber__cluster_control",
            "tool_input": {"action": "create_batch", "model": "tb172", "count": 10, "human_confirmed": True},
        }))
        updated = cleared["hookSpecificOutput"]["updatedInput"]
        self.assertFalse(updated["human_confirmed"])
        self.assertEqual(updated["count"], 10)
        untouched = asyncio.run(strip_model_confirmation({
            "tool_name": "mcp__vapor-chamber__cluster_line",
            "tool_input": {"action": "overview"},
        }))
        self.assertEqual(untouched, {})


class CardTests(unittest.TestCase):
    def test_long_list_becomes_a_table_and_short_list_stays_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "runs.json"
            payload.write_text(json.dumps({"runs": [{"run_id": f"R{i}", "machine_id": "M01", "passed": i % 2 == 0} for i in range(8)]}), encoding="utf-8")
            outside = root.parent / "secret.json"
            cards = present_cards("cluster_record", json.dumps({"ok": True, "full_file": str(payload)}), roots=[root])
            self.assertEqual(cards[0]["type"], "table")
            self.assertEqual(len(cards[0]["rows"]), 8)
            self.assertEqual(cards[0]["rows"][0][2], "—")
            short = root / "short.json"
            short.write_text(json.dumps({"runs": [{"run_id": "R1"}]}), encoding="utf-8")
            self.assertEqual(present_cards("cluster_record", json.dumps({"ok": True, "full_file": str(short)}), roots=[root]), [])
            self.assertEqual(present_cards("cluster_record", json.dumps({"ok": True, "full_file": str(outside)}), roots=[root]), [])

    def test_samples_become_a_chart_without_copying_every_point(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "samples.json"
            rows = []
            for index in range(200):
                rows.append({
                    "t_s": index * 0.5,
                    "power_w": 2.5,
                    "temps": [{"channel": "T0", "value": 40 + index / 100}, {"channel": "T1", "value": 25}],
                    "forces": [{"channel": "F1", "value": 100}],
                })
            payload.write_text(json.dumps({"samples": rows}), encoding="utf-8")
            cards = present_cards("cluster_record", json.dumps({"ok": True, "full_file": str(payload)}), roots=[root])
            self.assertEqual(cards[0]["type"], "chart")
            self.assertEqual(len(cards[0]["option"]["series"][0]["data"]), 80)
            self.assertEqual(cards[0]["option"]["xAxis"]["data"][-1], "99.5")

    def test_choice_fence_leaves_the_sentence_and_drops_the_markup(self) -> None:
        text, card = extract_choices('先看记录。\n```vc-choices\n[{"label":"看曲线","text":"看这条记录的温度曲线"}]\n```')
        self.assertEqual(text, "先看记录。")
        assert card is not None
        self.assertEqual(card["options"][0]["text"], "看这条记录的温度曲线")
        kept, missing = extract_choices("只有一句话。")
        self.assertEqual(kept, "只有一句话。")
        self.assertIsNone(missing)
        assistant = _named("AssistantMessage", content=[_named("TextBlock", text='结论如下。\n```vc-choices\n[{"label":"继续","text":"继续看下一条"}]\n```')])
        turn = turn_from_messages([assistant])
        self.assertEqual(turn["text"], "结论如下。")
        self.assertEqual(turn["blocks"][0]["type"], "choices")


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_unknown_module(self) -> None:
        with self.assertRaises(AppError) as caught:
            await AgentSessionService(None).create("u1", "agent.other")  # type: ignore[arg-type]
        self.assertEqual(caught.exception.status, 422)

    def test_scope_is_added_without_replacing_the_question(self) -> None:
        text = with_scope("  对比良率  ", " tb172 ", ["B-1", "B-1", " B-2 "])
        self.assertIn("型号：tb172", text)
        self.assertIn("批次：B-1、B-2", text)
        self.assertTrue(text.endswith("对比良率"))

    def test_empty_scope_leaves_the_question(self) -> None:
        self.assertEqual(with_scope("  只看这一句  ", "  ", []), "只看这一句")

    def test_titles_use_the_first_sentence(self) -> None:
        self.assertEqual(session_title("  给 HVP 做一个 3.5W 的方案  "), "给 HVP 做一个 3.5W 的方案")
        self.assertEqual(len(session_title("测" * 40)), 24)

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


class ToolListTests(unittest.TestCase):
    def test_keeps_every_cluster_tool(self) -> None:
        names = {item.removeprefix("mcp__vapor-chamber__") for item in MCP_TOOLS}
        self.assertEqual(
            names,
            {
                "cluster_guide",
                "cluster_line",
                "cluster_plan",
                "cluster_product",
                "cluster_record",
                "cluster_control",
                "cluster_compensation",
                "cluster_truth",
            },
        )


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
