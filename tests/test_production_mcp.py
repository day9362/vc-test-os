import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.dto.production import ProductionIn
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


class StartStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_posts_cluster_http(self) -> None:
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
        with patch("app.service.production.service.post_production", new=AsyncMock(return_value={"batch_id": "B-HVP1307G17-1-9725e9b1", "accepted": ["M01", "M02"], "queue_remaining": 8})) as http:
            with patch("app.service.production.service.push_production", new=AsyncMock()):
                with patch("app.service.production.service.push_batch", new=AsyncMock()):
                    result = await service.start(body, SimpleNamespace(user_id="limingyuan"), "k1")
        http.assert_awaited_once()
        self.assertEqual(http.await_args.args[0], "/fleet/production/start")
        self.assertEqual(result.batch_id, "B-HVP1307G17-1-9725e9b1")
        self.assertEqual(result.accepted, ["M01", "M02"])
        self.assertEqual(result.audit_id, "AUD-1")

    async def test_stop_posts_cluster_http(self) -> None:
        service = ProductionService(session=SimpleNamespace(commit=AsyncMock()), redis=None)
        batch = _batch(state="running", eta_s=1)
        current = SimpleNamespace(batch_id="B-1", active=True)
        service._cached = AsyncMock(return_value=None)
        service.repo.batch = AsyncMock(return_value=batch)
        service.repo.production = AsyncMock(return_value=current)
        service.audit.record = lambda *args, **kwargs: "AUD-2"
        service._store = AsyncMock()
        with patch("app.service.production.service.post_production", new=AsyncMock(return_value={})) as http:
            with patch("app.service.production.service.push_production", new=AsyncMock()):
                with patch("app.service.production.service.push_batch", new=AsyncMock()):
                    result = await service.stop("B-1", SimpleNamespace(user_id="limingyuan"), "k2")
        http.assert_awaited_once_with("/fleet/production/stop", {"batch_id": "B-1"})
        self.assertEqual(result.audit_id, "AUD-2")
        self.assertEqual(batch.state, "stopped")
        self.assertFalse(current.active)


if __name__ == "__main__":
    unittest.main()
