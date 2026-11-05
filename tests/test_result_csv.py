import unittest
from types import SimpleNamespace

from app.service.runs.result_csv import build_result_export, header_for, points_from_body, raw_filename, render_raw


def _row(**kwargs):
    base = dict(
        serial_number="SN-1",
        machine_id="M01",
        slot_index=2,
        plan_id="PLAN-1",
        plan_version=3,
        passed=False,
        fail_items=["Temp_T1-T2", "Force_F3"],
        rc=2.5,
        dt01=6.1,
        batch_id="B-1",
        ended_at=1762017000000,
        result={
            "duration_s": 180,
            "power_w": 3.5,
            "temps": [
                {"channel": "T0", "value": 70},
                {"channel": "T1", "value": 40},
                {"channel": "T14", "value": 31},
                {"channel": "Ta", "value": 25},
                {"channel": "Temp_T1_60s", "value": 99},
            ],
            "forces": [{"channel": "F3", "value": 120}],
            "deltas": {"Temp_T1-T2": 1.2},
        },
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


class ResultCsvTests(unittest.TestCase):
    def test_day_file_uses_our_names_and_drops_snapshot_columns(self):
        body, media, name = build_result_export(
            [_row()],
            {"B-1": "tb158"},
            {("PLAN-1", 3): 180},
            "day",
        )
        text = body.decode("utf-8-sig")
        header = text.splitlines()[0]
        self.assertEqual(media, "text/csv; charset=utf-8")
        self.assertTrue(name.endswith(".csv"))
        self.assertNotIn("60s", header)
        self.assertNotIn("Temp_", header)
        self.assertNotIn("run_id", header)
        self.assertIn("model,serial_number", header)
        self.assertIn("temp_t0", header)
        self.assertIn("temp_t1", header)
        self.assertIn("temp_t14", header)
        self.assertIn("temp_ambient", header)
        self.assertIn("delta_t0_t1", header)
        self.assertIn("delta_t1_t2", header)
        self.assertIn("force_3", header)
        self.assertIn("thermal_resistance", header)
        self.assertNotIn("temp_t2,", header)
        self.assertIn("tb158", text)
        self.assertIn("fail", text)
        self.assertIn("Temp_T1-T2;Force_F3", text)
        self.assertNotIn("|", text.splitlines()[1])

    def test_two_days_become_a_zip(self):
        later = _row(ended_at=1762017000000 + 86_400_000, serial_number="SN-2")
        body, media, name = build_result_export([_row(), later], {}, {}, "day")
        self.assertEqual(media, "application/zip")
        self.assertEqual(name, "results.zip")
        self.assertTrue(body.startswith(b"PK"))

    def test_products_group_is_one_file(self):
        later = _row(ended_at=1762017000000 + 86_400_000, serial_number="SN-2")
        body, media, name = build_result_export([_row(), later], {}, {}, "products")
        text = body.decode("utf-8-sig")
        self.assertEqual(media, "text/csv; charset=utf-8")
        self.assertEqual(name, "products.csv")
        self.assertEqual(text.count("\n"), 3)

    def test_batch_group_is_one_file_named_for_the_batch(self):
        _, media, name = build_result_export([_row(), _row(serial_number="SN-2")], {}, {}, "batch")
        self.assertEqual(media, "text/csv; charset=utf-8")
        self.assertEqual(name, "B-1.csv")

    def test_header_for_skips_snapshots(self):
        self.assertIsNone(header_for("Temp_T1_60s"))
        self.assertEqual(header_for("Temp_T0-T1"), "delta_t0_t1")
        self.assertEqual(header_for("Force_F14"), "force_14")

    def test_raw_filename_and_points(self):
        name = raw_filename("B-1", "SN/1", 1762017000000, "R1")
        self.assertTrue(name.startswith("B-1_SN_1_"))
        self.assertTrue(name.endswith(".csv"))
        points = points_from_body({
            "points": [{"t_s": 1, "temps": [{"channel": "T2", "value": 30}], "power_w": 3}],
        })
        text = render_raw(points)
        self.assertTrue(text.startswith("t_s,temp_t2,power_w"))
        self.assertIn("30", text)


if __name__ == "__main__":
    unittest.main()
