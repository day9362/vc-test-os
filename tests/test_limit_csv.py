import unittest

from app.service.products.boards import public_board
from app.service.runs.limit_csv import limit_map, render_csv


class LimitCsvTests(unittest.TestCase):
    def test_header_has_upper_and_lower_rows(self):
        limits = limit_map([{"item": "Temp_T0-T1", "low": 0.1, "high": 1.2, "skipped": False}])
        text = render_csv(["batch_id", "Temp_T0-T1"], limits, [{"batch_id": "B1", "Temp_T0-T1": 0.4}])
        rows = text.splitlines()
        self.assertEqual(rows[1].split(",")[0], "Upper Limited")
        self.assertEqual(rows[2].split(",")[0], "Lower Limited")
        self.assertIn("1.2", rows[1])
        self.assertIn("0.1", rows[2])

    def test_board_hides_grade_and_truth(self):
        board = public_board({
            "serial_number": "S1",
            "model": "A",
            "grade": "A",
            "defects": ["x"],
            "thermal_resistance": 1.2,
            "golden": True,
        })
        self.assertEqual(set(board), {"serial_number", "model", "golden"})


if __name__ == "__main__":
    unittest.main()
