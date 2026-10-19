import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.errors import AppError
from app.models.dto.production import ProductionIn
from app.service.production.mcp_agent import parse_tool_payload, start_args, stop_args
from app.service.production.service import ProductionService


def _machines() -> list[dict]:
    return [
        {"machine_id": "M01", "status": "READY", "comm_status": "OK", "plan_id": "PLAN-3f2c71d0", "plan_version": 3, "speed": 1, "slots": [{"phase": "IDLE"}]},
        {"machine_id": "M02", "status": "READY", "comm_status": "OK", "plan_id": "PLAN-3f2c71d0", "plan_version": 3, "speed": 1, "slots": [{"phase": "IDLE"}]},
    ]


def _batch(**extra) -> SimpleNamespace:
    values = dict(
        batch_id="B-HVP1307G17-1-9725e9b1", model="HVP1307G17-1", count=8, remaining=8,
        defect_ratio=0, batch_factor=1, state="running", tested=0, passed=0, failed=0, aborted=0,
        plan_id="PLAN-3f2c71d0", plan_version=3, machine_ids=["M01", "M02"], started_at=1,
        ended_at=None, rc_mean=0, rc_sd=0, top_fail="", eta_s=None,
    )
    values.update(extra)
    return SimpleNamespace(**values)


def _body() -> ProductionIn:
    return ProductionIn(
        machine_ids=["M01", "M02"],
        plan_id="PLAN-3f2c71d0",
        plan_version=3,
        batch_id="B-HVP1307G17-1-9725e9b1",
        auto_recover=True,
        max_count=None,
    )


class PayloadTests(unittest.TestCase):
    def test_start_args_go_to_vapor_chamber_test(self) -> None:
        args = start_args(_body())
        self.assertEqual(args["action"], "production")
        self.assertTrue(args["enable"])
        self.assertEqual(args["machine_ids"], ["M01", "M02"])
        self.assertEqual(args["plan_id"], "PLAN-3f2c71d0")
        self.assertEqual(args["plan_version"], 3)
        self.assertEqual(args["batch_id"], "B-HVP1307G17-1-9725e9b1")

    def test_stop_args_disable_production(self) -> None:
        self.assertEqual(stop_args("B-1"), {"action": "production", "enable": False, "batch_id": "B-1"})

    def test_parse_tool_payload_from_mcp_text(self) -> None:
        text = '已经开始。\n{"ok": true, "summary": "M01 开始连续测试", "data": {"batch_id": "B-1", "accepted": ["M01"]}}'
        payload = parse_tool_payload(text)
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["data"]["batch_id"], "B-1")

    def test_parse_tool_payload_from_content_blocks(self) -> None:
        content = [{"type": "text", "text": json.dumps({"ok": False, "summary": "机台正在测试"})}]
        payload = parse_tool_payload(content)
        self.assertEqual(payload["ok"], False)


class StartStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_calls_device_mcp_not_cluster_http(self) -> None:
        body = _body()
        service = ProductionService(session=SimpleNamespace(commit=AsyncMock(), add=lambda *_: None, flush=AsyncMock()), redis=None)
        context = {
            "plan_found": True,
            "plan_power": 3.5,
            "plan_name": "高压",
            "limits": [{"item": "power_w", "low": 3.4, "high": 3.6}],
            "model_power": 3.5,
            "remaining": 8,
            "batch_known": True,
            "machines": _machines(),
        }
        production = SimpleNamespace(active=False, batch_id="", queue_remaining=0, plan_id="", plan_version=0)
        batch = _batch()
        service._cached = AsyncMock(return_value=None)
        service._prepare = AsyncMock()
        service._context = AsyncMock(return_value=dict(context))
        service.repo.production = AsyncMock(return_value=None)
        service.repo.production_row = AsyncMock(return_value=production)
        service._touch_batch = AsyncMock(return_value=batch)
        service._dispatch = AsyncMock()
        service.audit.record = lambda *args, **kwargs: "AUD-1"
        service._store = AsyncMock()
        with patch("app.service.production.service.start_on_device", new=AsyncMock(return_value={"batch_id": "B-HVP1307G17-1-9725e9b1", "accepted": ["M01", "M02"], "queue_remaining": 8})) as device:
            with patch("app.service.production.service.push_production", new=AsyncMock()):
                with patch("app.service.production.service.push_batch", new=AsyncMock()):
                    with patch("app.service.production.service.post_production", create=True, new=AsyncMock()) as http:
                        result = await service.start(body, SimpleNamespace(user_id="limingyuan"), "k1")
        device.assert_awaited_once()
        http.assert_not_called()
        self.assertEqual(result.batch_id, "B-HVP1307G17-1-9725e9b1")
        self.assertEqual(result.accepted, ["M01", "M02"])
        self.assertEqual(result.audit_id, "AUD-1")

    async def test_start_maps_mcp_failure(self) -> None:
        from app.service.production.mcp_agent import McpCallError

        body = _body()
        service = ProductionService(session=SimpleNamespace(), redis=None)
        service._cached = AsyncMock(return_value=None)
        service._prepare = AsyncMock()
        service._context = AsyncMock(return_value={
            "plan_found": True, "plan_power": 3.5, "plan_name": "高压",
            "limits": [{"item": "power_w"}], "model_power": 3.5, "remaining": 8,
            "batch_known": True, "machines": _machines(),
        })
        service.repo.production = AsyncMock(return_value=None)
        with patch("app.service.production.service.start_on_device", new=AsyncMock(side_effect=McpCallError("设备层拒绝了这次下发", {"ok": False}))):
            with self.assertRaises(AppError) as raised:
                await service.start(body, SimpleNamespace(user_id="limingyuan"), "k1")
        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(raised.exception.code, "CLUSTER_ERROR")

if __name__ == "__main__":
    unittest.main()
