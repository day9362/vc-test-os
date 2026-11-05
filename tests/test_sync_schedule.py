import unittest

from app.tasks.scheduler import job_plan


class SyncScheduleTest(unittest.TestCase):
    def test_seven_rows_keep_their_own_interval_and_switch(self):
        payload = {"jobs": [
            {"key": "slots", "interval_s": 1, "enabled": True},
            {"key": "machine", "interval_s": 10, "enabled": False},
            {"key": "runs", "interval_s": 5, "enabled": True},
            {"key": "samples", "interval_s": 2, "enabled": True},
            {"key": "plans", "interval_s": 60, "enabled": False},
            {"key": "batches", "interval_s": 300, "enabled": True},
            {"key": "calib", "interval_s": 60, "enabled": True},
        ]}
        plan = {key: (seconds, enabled) for key, seconds, enabled in job_plan(payload)}
        self.assertEqual(plan["slots"], (1, True))
        self.assertEqual(plan["machine"], (10, False))
        self.assertEqual(plan["runs"], (5, True))
        self.assertEqual(plan["samples"], (2, True))
        self.assertEqual(plan["plans"], (60, False))
        self.assertEqual(plan["batches"], (300, True))
        self.assertEqual(plan["calib"], (60, True))

    def test_missing_row_uses_default(self):
        plan = {key: (seconds, enabled) for key, seconds, enabled in job_plan({})}
        self.assertEqual(plan["runs"], (5, True))
        self.assertEqual(plan["batches"], (300, True))


if __name__ == "__main__":
    unittest.main()
