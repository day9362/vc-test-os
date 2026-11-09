import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.errors import AppError
from app.models.dto.production import BatchCreateIn
from app.service.machines.slot_service import SlotCommandService
from app.service.production.batch_service import BatchCommandService

USER = SimpleNamespace(user_id="u-1")


def _machine(**extra) -> SimpleNamespace:
    values = dict(machine_id="M01", status="READY", comm_status="OK", plan_id="PLAN-1", plan_version=2, last_sync_at=0, slot_count=4)
    values.update(extra)
    return SimpleNamespace(**values)


def _slot(**extra) -> SimpleNamespace:
    values = dict(index=1, phase="IDLE", serial_number=None, last_error="", progress=0, power_w=0, run_id=None)
    values.update(extra)
    return SimpleNamespace(**values)


def _service(machine, slot, run=None) -> SlotCommandService:
    added = []
    session = SimpleNamespace(commit=AsyncMock(), add=added.append, get=AsyncMock(return_value=run))
    service = SlotCommandService(session, redis=None)
    service.added = added
    service._require_online = AsyncMock(return_value=(machine, [slot]))
    service._publish = AsyncMock()
    service.audit = MagicMock()
    service.audit.record.return_value = "AUD-1"
    return service


class SlotCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_sets_serial(self) -> None:
        slot = _slot()
        service = _service(_machine(), slot)
        with patch("app.service.machines.slot_service.post_cluster", AsyncMock(return_value={"ok": True})) as cluster:
            out = await service.load("M01", 1, " SN-1 ", USER, None)
        cluster.assert_awaited_once_with("/machines/M01/slots/1/load", {"serial_number": "SN-1"})
        self.assertEqual(slot.serial_number, "SN-1")
        self.assertEqual(slot.phase, "LOADED")
        self.assertEqual(out.serial_number, "SN-1")

    async def test_load_rejects_busy_slot(self) -> None:
        service = _service(_machine(), _slot(phase="SAMPLING"))
        with patch("app.service.machines.slot_service.post_cluster", AsyncMock()) as cluster:
            with self.assertRaises(AppError) as caught:
                await service.load("M01", 1, "SN-1", USER, None)
        self.assertEqual(caught.exception.status, 409)
        cluster.assert_not_awaited()

    async def test_start_creates_running_run(self) -> None:
        slot = _slot(serial_number="SN-1")
        service = _service(_machine(), slot)
        with patch("app.service.machines.slot_service.post_cluster", AsyncMock(return_value={"run_id": "R-9"})) as cluster:
            out = await service.start("M01", 1, USER, None)
        cluster.assert_awaited_once_with("/machines/M01/slots/1/test", None)
        self.assertEqual(out.run_id, "R-9")
        self.assertEqual(slot.phase, "SAMPLING")
        run = service.added[0]
        self.assertEqual((run.run_id, run.status, run.plan_id, run.serial_number), ("R-9", "RUNNING", "PLAN-1", "SN-1"))

    async def test_start_without_run_id_does_not_invent_one(self) -> None:
        slot = _slot(serial_number="SN-1", phase="LOADED")
        service = _service(_machine(), slot)
        with patch("app.service.machines.slot_service.post_cluster", AsyncMock(return_value={})):
            with self.assertRaises(AppError) as caught:
                await service.start("M01", 1, USER, None)
        self.assertEqual(caught.exception.status, 502)
        self.assertEqual(service.added, [])
        self.assertNotEqual(slot.phase, "SAMPLING")

    async def test_start_needs_loaded_board(self) -> None:
        service = _service(_machine(), _slot())
        with self.assertRaises(AppError):
            await service.start("M01", 1, USER, None)

    async def test_start_refuses_faulted_machine(self) -> None:
        service = _service(_machine(status="FAULT"), _slot(serial_number="SN-1"))
        with self.assertRaises(AppError):
            await service.start("M01", 1, USER, None)

    async def test_abort_marks_run_aborted(self) -> None:
        run = SimpleNamespace(status="RUNNING", passed=None, ended_at=0)
        slot = _slot(phase="SAMPLING", serial_number="SN-1", run_id="R-9")
        service = _service(_machine(), slot, run)
        with patch("app.service.machines.slot_service.post_cluster", AsyncMock(return_value={})):
            out = await service.abort("M01", 1, USER, None)
        self.assertEqual(run.status, "ABORTED")
        self.assertGreater(run.ended_at, 0)
        self.assertEqual((slot.phase, slot.run_id, slot.serial_number), ("IDLE", None, None))
        self.assertEqual(out.phase, "IDLE")

    async def test_clear_error_returns_slot_to_idle(self) -> None:
        slot = _slot(phase="ERROR", last_error="真空不足")
        service = _service(_machine(), slot)
        with patch("app.service.machines.slot_service.post_cluster", AsyncMock(return_value={})):
            await service.clear_error("M01", 1, USER, None)
        self.assertEqual((slot.phase, slot.last_error), ("IDLE", ""))

    async def test_missing_slot(self) -> None:
        service = _service(_machine(), _slot(index=2))
        with self.assertRaises(AppError) as caught:
            await service.clear_error("M01", 1, USER, None)
        self.assertEqual(caught.exception.status, 404)


class BatchCreateTests(unittest.IsolatedAsyncioTestCase):
    def _service(self) -> BatchCommandService:
        service = BatchCommandService(SimpleNamespace(commit=AsyncMock()), redis=None)
        service.repo = SimpleNamespace(
            models=AsyncMock(return_value=[SimpleNamespace(model="tb172")]),
            batch=AsyncMock(return_value=None),
            save_batch=AsyncMock(),
        )
        service.audit = MagicMock()
        service.audit.record.return_value = "AUD-2"
        return service

    async def test_create_saves_batch(self) -> None:
        service = self._service()
        upstream = {"batch": {"batch_id": "B-1", "model": "tb172", "count": 2, "defect_ratio": 0.5, "batch_factor": 1.0}, "serial_numbers": ["S1", "S2"]}
        with patch("app.service.production.batch_service.post_production", AsyncMock(return_value=upstream)) as cluster:
            out = await service.create(BatchCreateIn(model="tb172", count=2, defect_ratio=0.5), USER, None)
        cluster.assert_awaited_once()
        self.assertEqual(out.batch.batch_id, "B-1")
        self.assertEqual(out.batch.remaining, 2)
        self.assertEqual(out.serial_numbers, ["S1", "S2"])
        service.repo.save_batch.assert_awaited_once()

    async def test_unknown_model(self) -> None:
        service = self._service()
        with self.assertRaises(AppError) as caught:
            await service.create(BatchCreateIn(model="nope", count=2), USER, None)
        self.assertEqual(caught.exception.status, 422)

    async def test_no_cluster(self) -> None:
        service = self._service()
        with patch("app.service.production.batch_service.post_production", AsyncMock(return_value=None)):
            with self.assertRaises(AppError) as caught:
                await service.create(BatchCreateIn(model="tb172", count=2), USER, None)
        self.assertEqual(caught.exception.status, 409)


if __name__ == "__main__":
    unittest.main()
