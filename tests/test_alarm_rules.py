import unittest

from app.core.config import settings
from app.service.overview.rules import alarm_rules_from, escalate_alarm, matched_we_rules


def _flat(center: float, count: int) -> list[float]:
    return [center + (0.05 if index % 2 else -0.05) for index in range(count)]


class AlarmRulesTest(unittest.TestCase):
    def test_saved_flags_override_the_defaults(self) -> None:
        rules = alarm_rules_from({
            "rules": {
                "drift_c": 0.4,
                "we_rules": [],
                "sentinel_as_data_anomaly": False,
                "degraded_alarm": False,
                "ack_timeout_min": 0,
            }
        })
        self.assertEqual(rules.drift_c, 0.4)
        self.assertEqual(rules.we_rules, ())
        self.assertFalse(rules.sentinel_as_data_anomaly)
        self.assertFalse(rules.degraded_alarm)
        self.assertEqual(rules.ack_timeout_min, 0)

    def test_missing_rules_keep_the_previous_defaults(self) -> None:
        rules = alarm_rules_from({})
        self.assertEqual(rules.drift_c, settings.drift_c)
        self.assertEqual(rules.we_rules, ("WE-1", "WE-2", "WE-4"))
        self.assertTrue(rules.sentinel_as_data_anomaly)
        self.assertEqual(rules.degraded_alarm, settings.degraded_alarm)
        self.assertEqual(rules.ack_timeout_min, 15)

    def test_we4_flags_eight_points_on_one_side(self) -> None:
        samples = [0.02] * 8 + _flat(0, 16)
        self.assertEqual(matched_we_rules(samples, ("WE-4",)), ["WE-4"])
        self.assertEqual(matched_we_rules(samples, ()), [])

    def test_we1_flags_one_point_past_three_sigma(self) -> None:
        samples = [0.20] + _flat(0, 20)
        self.assertIn("WE-1", matched_we_rules(samples, ("WE-1", "WE-2", "WE-3", "WE-4")))

    def test_ack_timeout_raises_the_level_once(self) -> None:
        alarm = type("Alarm", (), {"acked": False, "level": "major", "time": 0, "message": "通信降级"})()
        self.assertTrue(escalate_alarm(alarm, 15 * 60_000, 15))
        self.assertEqual(alarm.level, "critical")
        self.assertIn("超时未确认已升级", alarm.message)
        self.assertFalse(escalate_alarm(alarm, 40 * 60_000, 15))
        self.assertEqual(alarm.level, "critical")

    def test_ack_timeout_zero_does_not_escalate(self) -> None:
        alarm = type("Alarm", (), {"acked": False, "level": "minor", "time": 0, "message": "哨兵值"})()
        self.assertFalse(escalate_alarm(alarm, 60 * 60_000, 0))
        self.assertEqual(alarm.level, "minor")
