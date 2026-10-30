import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.errors import AppError
from app.service.production.sync import CatalogSync, apply_run_stats


def _batch(**extra) -> SimpleNamespace:
    values = dict(
        batch_id="B-1",
        model="tb172",
        count=1,
        remaining=1,
        remaining_locked=True,
        state="running",
        tested=0,
        passed=0,
        failed=0,
        aborted=0,
        plan_id="PLAN-1",
        plan_version=1,
        machine_ids=["M01"],
        started_at=1,
        ended_at=None,
        rc_mean=0,
        rc_sd=0,
        top_fail="",
        eta_s=None,
    )
    values.update(extra)
    return SimpleNamespace(**values)


def _production(**extra) -> SimpleNamespace:
    values = dict(active=True, batch_id="B-1", queue_remaining=1, plan_id="PLAN-1", plan_version=1)
    values.update(extra)
    return SimpleNamespace(**values)


class ApplyRunStatsTests(unittest.TestCase):
    def test_inactive_running_batch_becomes_done(self) -> None:
        row = _batch()
        production = _production(active=False)
        apply_run_stats(row, [], production)
        self.assertEqual(row.state, "done")
        self.assertFalse(row.remaining_locked)
        self.assertEqual(row.remaining, 1)

    def test_active_with_empty_queue_closes_even_without_runs(self) -> None:
        row = _batch(remaining=0, remaining_locked=True)
        production = _production(queue_remaining=0)
        apply_run_stats(row, [], production)
        self.assertEqual(row.state, "done")
        self.assertFalse(production.active)

    def test_active_open_batch_stays_running(self) -> None:
        row = _batch()
        production = _production()
        apply_run_stats(row, [], production)
        self.assertEqual(row.state, "running")
        self.assertTrue(production.active)

    def test_catalog_batch_without_state_stays_untouched(self) -> None:
        row = _batch(state="", remaining=3, tested=0)
        production = _production(active=False, batch_id="")
        apply_run_stats(row, [], production)
        self.assertEqual(row.state, "")


class ProductionSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_404_clears_active(self) -> None:
        row = _production(active=True, batch_id="B-stuck")
        repo = SimpleNamespace(production_row=AsyncMock(return_value=row))
        sync = CatalogSync(session=SimpleNamespace())
        sync.repo = repo
        with patch("app.service.production.sync.get_cluster", new=AsyncMock(return_value=None)):
            await sync._production()
        self.assertFalse(row.active)
        self.assertEqual(row.queue_remaining, 0)

    async def test_production_timeout_then_empty_clears_active(self) -> None:
        row = _production(active=True, batch_id="B-stuck")
        repo = SimpleNamespace(production_row=AsyncMock(return_value=row))
        sync = CatalogSync(session=SimpleNamespace())
        sync.repo = repo

        async def fake_get(path: str):
            if path == "/fleet/production":
                raise AppError(504, "CLUSTER_TIMEOUT", "请求集群超时")
            return None

        with patch("app.service.production.sync.get_cluster", new=AsyncMock(side_effect=fake_get)):
            await sync._production()
        self.assertFalse(row.active)

    async def test_production_all_errors_keeps_active(self) -> None:
        row = _production(active=True, batch_id="B-stuck")
        repo = SimpleNamespace(production_row=AsyncMock(return_value=row))
        sync = CatalogSync(session=SimpleNamespace())
        sync.repo = repo
        with patch(
            "app.service.production.sync.get_cluster",
            new=AsyncMock(side_effect=AppError(504, "CLUSTER_TIMEOUT", "请求集群超时")),
        ):
            await sync._production()
        self.assertTrue(row.active)


if __name__ == "__main__":
    unittest.main()
