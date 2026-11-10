import unittest
from types import SimpleNamespace

from app.service.runs.cluster_ingest import _apply_payload


def _row(t_s: float) -> SimpleNamespace:
    return SimpleNamespace(
        result={"t_s": t_s, "temps": [{"channel": "T0", "value": 44}], "deltas": {"Rc": 5.0}},
        machine_id="M01",
        slot_index=1,
        serial_number="SN",
        plan_id="PLAN-1",
        plan_version=1,
        status="COMPLETED",
        passed=False,
        fail_items=["Temp_T1-T5"],
        keep_result=True,
        rc=5.0,
        dt01=2.1,
        batch_id="B-1",
        ended_at=1,
    )


class RunSnapshotTests(unittest.TestCase):
    def test_earlier_sample_does_not_replace_the_finished_point(self):
        row = _row(180)
        _apply_payload(
            row,
            {"result": {"t_s": 55, "temps": [{"channel": "T0", "value": 38}], "deltas": {"Rc": 3.3}}, "status": "COMPLETED"},
            fill_result=True,
        )
        self.assertEqual(row.result["t_s"], 180)
        self.assertEqual(row.rc, 5.0)

    def test_later_sample_replaces_the_midpoint(self):
        row = _row(55)
        _apply_payload(
            row,
            {"result": {"t_s": 180, "temps": [{"channel": "T0", "value": 44}], "deltas": {"Rc": 5.1}}, "status": "COMPLETED"},
            fill_result=True,
        )
        self.assertEqual(row.result["t_s"], 180)
        self.assertAlmostEqual(row.rc, 5.1)


if __name__ == "__main__":
    unittest.main()
