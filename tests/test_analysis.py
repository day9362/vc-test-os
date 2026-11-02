import unittest

from app.service.reports.analysis_math import correlate, fail_groups, item_sort_key, process_shape, summarize, usable
from app.service.reports.analysis_service import _spec


def _row(value, low=0, high=10, serial="S", ended=0, run="R", invalid=0):
    return {
        "run_id": run,
        "serial": serial,
        "value": value,
        "low": low,
        "high": high,
        "ended_at": ended,
        "invalid": invalid,
    }


class AnalysisMathTests(unittest.TestCase):
    def test_invalid_readings_are_not_usable(self):
        self.assertFalse(usable(99999))
        self.assertFalse(usable(-1))
        self.assertTrue(usable(2.5))

    def test_summarize_reports_spread_offset_and_retest(self):
        rows = [
            _row(2, serial="A", ended=1, run="1"),
            _row(4, serial="A", ended=2, run="2"),
            _row(9, serial="B", ended=3, run="3"),
            _row(11, serial="C", ended=4, run="4"),
        ]
        item = summarize("T1", rows)
        self.assertEqual(item["n"], 4)
        self.assertEqual(item["minimum"], 2)
        self.assertEqual(item["maximum"], 11)
        self.assertEqual(item["high_fail"], 1)
        self.assertEqual(item["retest_serials"], 1)
        self.assertEqual(item["retest_range"], 2)
        self.assertEqual(item["offset"], "居中")
        self.assertEqual(item["trend"], "后半段升高")
        self.assertIsNone(item["cpk"])

    def test_correlation_counts_items_that_fail_together(self):
        rows = []
        for index, (left, right) in enumerate([(1, 2), (2, 3), (3, 4), (4, 5), (11, 12)]):
            rows.append({**_row(left, run=str(index), serial=str(index)), "item": "T1"})
            rows.append({**_row(right, run=str(index), serial=str(index)), "item": "T2"})
        pairs = correlate(rows)
        self.assertEqual(pairs[0]["co_fail"], 1)
        self.assertGreater(pairs[0]["r"], 0.9)

    def test_fail_groups_split_single_and_multiple_items(self):
        rows = []
        for run, items in (("a", ["Temp_T1-T2"]), ("b", ["Temp_T1-T2"]), ("c", ["Temp_T0-T1", "Temp_T1-T4", "Temp_T1-T5"])):
            for item in items:
                rows.append({"run_id": run, "item": item, "value": 9, "low": 0, "high": 1})
            rows.append({"run_id": run, "item": "power_w", "value": 2.5, "low": 2.4, "high": 2.6})
        groups = fail_groups(rows)
        self.assertEqual(groups[0], {"items": ["Temp_T1-T2"], "count": 2})
        self.assertEqual(groups[1]["count"], 1)
        self.assertEqual(groups[1]["items"], ["Temp_T0-T1", "Temp_T1-T4", "Temp_T1-T5"])

    def test_temp_items_sort_by_point_number(self):
        names = ["Temp_T1-T5", "power_w", "Temp_T1-T10", "Temp_T0-T1", "Temp_T1-T2"]
        self.assertEqual(sorted(names, key=item_sort_key), ["Temp_T0-T1", "Temp_T1-T2", "Temp_T1-T5", "Temp_T1-T10", "power_w"])

    def test_plan_limits_map_onto_result_channels(self):
        spec = _spec([
            {"item": "Temp_T0-T1", "low": 0, "high": 5, "skipped": False},
            {"item": "Temp_T1-T4_60s", "low": 0, "high": 3, "skipped": False},
            {"item": "power_w", "low": 2.4, "high": 2.6, "skipped": False},
        ])
        self.assertEqual(spec["delta_t0_t1"], ("Temp_T0-T1", 0, 5))
        self.assertEqual(spec["power_w"][0], "power_w")
        self.assertNotIn("Temp_T1-T4_60s", {name for name, *_ in spec.values()})

    def test_process_shape_distinguishes_a_late_crossing(self):
        self.assertEqual(process_shape([1, 1, 1, 1, 1, 1, 1, 1, 12, 12], 0, 10), "结束前超上限")
        self.assertEqual(process_shape([12, 12, 12, 12, 1, 1], 0, 10), "全程超上限")


if __name__ == "__main__":
    unittest.main()
