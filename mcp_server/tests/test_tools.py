import base64
import json
import unittest

import httpx

from app.approval import MemoryStore, sign
from app.backend import Backend
from app.config import settings
from app.identity import Identity, force_identity
from app.state import set_backend, set_store
from app.tools.alarm import vc_alarm
from app.tools.board import vc_board
from app.tools.machine import vc_machine
from app.tools.run import vc_run


def _token(sub: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"h.{payload}.s"


MACHINES = [
    {
        "machine_id": "VC-01",
        "status": "RUNNING",
        "comm_status": "ONLINE",
        "slots": [{"index": 1, "phase": "SAMPLING", "run_id": "R1", "progress": 40}, {"index": 2, "phase": "IDLE"}],
    },
    {"machine_id": "VC-02", "status": "IDLE", "comm_status": "DISCONNECTED", "slots": [{"index": 1, "phase": "IDLE"}]},
]


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict | None]] = []
        self.routes: dict[tuple[str, str], tuple[int, object]] = {}

    def route(self, method: str, path: str, status: int, body: object) -> None:
        self.routes[(method, path)] = (status, body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, dict(request.headers), body))
        if (request.method, path) == ("POST", "/auth/login"):
            return httpx.Response(200, json={"token": "service-token"})
        found = self.routes.get((request.method, path))
        if found is None:
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": f"no route {path}"}})
        status, payload = found
        return httpx.Response(status, json=payload)

    def sent(self, method: str, path: str) -> list[tuple[str, str, dict, dict | None]]:
        return [call for call in self.calls if call[0] == method and call[1] == path]


class ToolTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.saved = (settings.mcp_approval_secret, settings.vc_username, settings.vc_password, settings.vc_tenant)
        settings.mcp_approval_secret = "test-secret"
        settings.vc_tenant, settings.vc_username, settings.vc_password = "line-a", "svc", "pw"
        self.fake = FakeBackend()
        self.backend = Backend("http://backend/api/v1", httpx.MockTransport(self.fake.handler))
        set_backend(self.backend)
        set_store(MemoryStore())
        self.token = _token("u-1")
        self.forced = force_identity(Identity(self.token))

    async def asyncTearDown(self) -> None:
        await self.backend.aclose()
        set_backend(None)
        set_store(None)
        force_identity(None)
        settings.mcp_approval_secret, settings.vc_username, settings.vc_password, settings.vc_tenant = self.saved


class ReadTests(ToolTestCase):
    async def test_machines_summarizes_fleet(self):
        self.fake.route("GET", "/machines", 200, MACHINES)
        result = await vc_machine("machines")
        self.assertTrue(result["ok"], result)
        self.assertIn("VC-01", json.dumps(result, ensure_ascii=False))

    async def test_readonly_reads_with_service_account(self):
        force_identity(Identity())
        self.fake.route("GET", "/machines", 200, MACHINES)
        result = await vc_machine("machines")
        self.assertTrue(result["ok"], result)
        call = self.fake.sent("GET", "/machines")[0]
        self.assertEqual(call[2]["authorization"], "Bearer service-token")

    async def test_user_token_is_forwarded(self):
        self.fake.route("GET", "/machines", 200, MACHINES)
        await vc_machine("machines")
        self.assertEqual(self.fake.sent("GET", "/machines")[0][2]["authorization"], f"Bearer {self.token}")

    async def test_backend_down_is_reported(self):
        def down(request):
            raise httpx.ConnectError("refused")

        await self.backend.aclose()
        self.backend = Backend("http://backend/api/v1", httpx.MockTransport(down))
        set_backend(self.backend)
        result = await vc_machine("machines")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "BACKEND_UNAVAILABLE")

    async def test_missing_argument(self):
        result = await vc_run("run")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "BAD_ARGUMENT")


class WriteTests(ToolTestCase):
    async def test_readonly_cannot_write(self):
        force_identity(Identity())
        result = await vc_alarm("ack", alarm_ids=["A1"])
        self.assertEqual(result["error"]["code"], "FORBIDDEN")
        self.assertEqual(self.fake.sent("POST", "/alarms/A1/ack"), [])

    async def test_low_risk_runs_directly(self):
        self.fake.route("POST", "/alarms/A1/ack", 200, {"alarm": {}, "audit_id": "AU1"})
        self.fake.route("POST", "/alarms/A2/ack", 409, {"error": {"code": "CONFLICT", "message": "已确认"}})
        result = await vc_alarm("ack", alarm_ids=["A1", "A2"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["done"], ["A1"])
        self.assertEqual(result["data"]["failed"][0]["alarm_id"], "A2")

    async def test_approval_flow(self):
        self.fake.route("GET", "/machines", 200, MACHINES)
        self.fake.route("POST", "/machines/VC-01/power-off", 200, {"status": "OFF", "audit_id": "AU1"})
        first = await vc_machine("power_off", machine_ids=["VC-01"])
        self.assertEqual(first["error"]["code"], "APPROVAL_REQUIRED")
        card = first["approval"]
        self.assertEqual(card["risk"], "high")
        self.assertTrue(any("1 号槽正在测试" in item for item in card["effects"]), card)
        self.assertEqual(self.fake.sent("POST", "/machines/VC-01/power-off"), [])

        wrong = await vc_machine("power_off", confirm_id=card["confirm_id"], approval="bad")
        self.assertEqual(wrong["error"]["code"], "APPROVAL_INVALID")

        good = sign(card["confirm_id"])
        done = await vc_machine("power_off", confirm_id=card["confirm_id"], approval=good)
        self.assertTrue(done["ok"], done)
        call = self.fake.sent("POST", "/machines/VC-01/power-off")[0]
        self.assertEqual(call[2]["idempotency-key"], f"{card['confirm_id']}:VC-01")

        again = await vc_machine("power_off", confirm_id=card["confirm_id"], approval=good)
        self.assertEqual(again["error"]["code"], "APPROVAL_INVALID")
        self.assertEqual(len(self.fake.sent("POST", "/machines/VC-01/power-off")), 1)

    async def test_approval_ignores_new_arguments(self):
        self.fake.route("GET", "/machines", 200, MACHINES)
        self.fake.route("POST", "/machines/VC-01/power-on", 200, {"status": "IDLE"})
        card = (await vc_machine("power_on", machine_ids=["VC-01"]))["approval"]
        await vc_machine("power_on", machine_ids=["VC-02"], confirm_id=card["confirm_id"], approval=sign(card["confirm_id"]))
        self.assertEqual(len(self.fake.sent("POST", "/machines/VC-01/power-on")), 1)
        self.assertEqual(self.fake.sent("POST", "/machines/VC-02/power-on"), [])

    async def test_approval_must_be_same_user(self):
        self.fake.route("GET", "/machines", 200, MACHINES)
        card = (await vc_machine("power_on", machine_ids=["VC-01"]))["approval"]
        force_identity(Identity(_token("u-2")))
        result = await vc_machine("power_on", confirm_id=card["confirm_id"], approval=sign(card["confirm_id"]))
        self.assertEqual(result["error"]["code"], "APPROVAL_INVALID")

    async def test_approval_must_match_action(self):
        self.fake.route("GET", "/machines", 200, MACHINES)
        card = (await vc_machine("power_on", machine_ids=["VC-01"]))["approval"]
        result = await vc_machine("power_off", confirm_id=card["confirm_id"], approval=sign(card["confirm_id"]))
        self.assertEqual(result["error"]["code"], "APPROVAL_INVALID")

    async def test_partial_failure_across_machines(self):
        self.fake.route("GET", "/machines", 200, MACHINES)
        self.fake.route("POST", "/machines/VC-01/reset", 200, {"status": "IDLE"})
        self.fake.route("POST", "/machines/VC-02/reset", 503, {"error": {"code": "MACHINE_OFFLINE", "message": "机台离线"}})
        card = (await vc_machine("reset", machine_ids=["VC-01", "VC-02"]))["approval"]
        result = await vc_machine("reset", confirm_id=card["confirm_id"], approval=sign(card["confirm_id"]))
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "PARTIAL")
        self.assertEqual([d["machine_id"] for d in result["error"]["detail"]["done"]], ["VC-01"])
        self.assertEqual(result["error"]["detail"]["failed"][0]["code"], "MACHINE_OFFLINE")
        again = await vc_machine("reset", confirm_id=card["confirm_id"], approval=sign(card["confirm_id"]))
        self.assertNotEqual(again["error"]["code"], "APPROVAL_INVALID")

    async def test_reset_without_ids_targets_online_machines(self):
        self.fake.route("GET", "/machines", 200, MACHINES)
        card = (await vc_machine("reset"))["approval"]
        self.assertEqual(card["arguments"]["machine_ids"], ["VC-01"])

    async def test_unknown_machine(self):
        self.fake.route("GET", "/machines", 200, MACHINES)
        result = await vc_machine("power_on", machine_ids=["VC-99"])
        self.assertEqual(result["error"]["code"], "NOT_FOUND")

    async def test_slot_load_refuses_busy_slot(self):
        self.fake.route("GET", "/machines/VC-01", 200, MACHINES[0])
        result = await vc_machine("slot_load", machine_id="VC-01", slot_index=1, serial_number="SN1")
        self.assertEqual(result["error"]["code"], "CONFLICT")

    async def test_production_start_blocks_on_danger(self):
        self.fake.route("POST", "/production/precheck", 200, {"issues": [{"level": "danger", "message": "方案未发布"}]})
        result = await vc_machine("production_start", machine_ids=["VC-01"], plan_id="P1", plan_version=1, batch_id="B1")
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("方案未发布", result["summary"])

    async def test_compensation_preview_shows_values(self):
        self.fake.route("GET", "/machines/VC-01/compensation", 200, {"items": [{"channel": "T1", "value": 0.1}]})
        result = await vc_machine("apply_compensation", machine_id="VC-01", mode="add", items=[{"channel": "T1", "value": 0.2}])
        self.assertEqual(result["error"]["code"], "APPROVAL_REQUIRED")
        self.assertIn("+0.100 → +0.300", result["approval"]["effects"][0])

    async def test_power_on_without_machines_asks_for_ids(self):
        self.fake.route("GET", "/machines", 200, MACHINES)
        result = await vc_machine("power_on")
        self.assertEqual(result["error"]["code"], "BAD_ARGUMENT")
        self.assertNotIn("可复位", result["summary"])

    async def test_rejected_execute_keeps_approval(self):
        self.fake.route("GET", "/machines", 200, MACHINES)
        self.fake.route("POST", "/machines/VC-01/power-on", 409, {"error": {"code": "CONFLICT", "message": "请先复位"}})
        card = (await vc_machine("power_on", machine_ids=["VC-01"]))["approval"]
        first = await vc_machine("power_on", confirm_id=card["confirm_id"], approval=sign(card["confirm_id"]))
        self.assertFalse(first["ok"])
        self.fake.route("POST", "/machines/VC-01/power-on", 200, {"status": "IDLE"})
        second = await vc_machine("power_on", confirm_id=card["confirm_id"], approval=sign(card["confirm_id"]))
        self.assertTrue(second["ok"], second)

    async def test_create_batch_needs_approval(self):
        self.fake.route("GET", "/models", 200, [{"model": "A1", "power_w": 2.5}])
        result = await vc_board("create_batch", model="A1", count=2, yield_rate=1)
        self.assertEqual(result["error"]["code"], "APPROVAL_REQUIRED")
        self.assertEqual(result["approval"]["arguments"]["count"], 2)
        self.assertEqual(result["approval"]["arguments"]["defect_ratio"], 0)

    async def test_speed_without_machines_is_rejected(self):
        result = await vc_machine("sim_speed", speed=2)
        self.assertEqual(result["error"]["code"], "BAD_ARGUMENT")

    async def test_delete_draft_needs_approval_without_plan_body(self):
        from app.tools.plan import vc_plan

        result = await vc_plan("delete_draft", plan_id="P1")
        self.assertEqual(result["error"]["code"], "APPROVAL_REQUIRED")
        self.assertIn("删除草稿", result["approval"]["sentence"])

    async def test_approval_without_secret(self):
        settings.mcp_approval_secret = ""
        result = await vc_alarm("ack_all", confirm_id="cf_x", approval="y")
        self.assertEqual(result["error"]["code"], "APPROVAL_INVALID")


if __name__ == "__main__":
    unittest.main()
