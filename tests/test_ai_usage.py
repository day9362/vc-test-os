import unittest
from datetime import datetime

from app.core.errors import AppError
from app.service.ai.catalog import cost_cny
from app.service.ai.usage import month_start, over_budget, should_alert, window_start


class UsageMathTests(unittest.TestCase):
    def test_prices_input_and_output_per_million(self) -> None:
        self.assertAlmostEqual(cost_cny("deepseek-v3", 1_000_000, 1_000_000), 10)
        self.assertAlmostEqual(cost_cny("qwen3-max", 1_000_000, 0), 6)
        self.assertEqual(cost_cny("rule", 100, 100), 0)

    def test_custom_price_overrides_the_public_rate(self) -> None:
        self.assertAlmostEqual(cost_cny("deepseek-v3", 1_000_000, 0, {"deepseek-v3": {"input": 3, "output": 9}}), 3)

    def test_window_covers_the_requested_number_of_days(self) -> None:
        now = int(datetime(2026, 10, 27, 18, 0).timestamp() * 1000)
        start = datetime.fromtimestamp(window_start(now, 7) / 1000)
        self.assertEqual((start.year, start.month, start.day, start.hour), (2026, 10, 21, 0))

    def test_month_starts_on_the_first(self) -> None:
        now = int(datetime(2026, 10, 27, 18, 0).timestamp() * 1000)
        start = datetime.fromtimestamp(month_start(now) / 1000)
        self.assertEqual((start.month, start.day, start.hour), (10, 1, 0))

    def test_alert_and_pause_follow_the_budget(self) -> None:
        self.assertFalse(should_alert(79, 100, 80))
        self.assertTrue(should_alert(80, 100, 80))
        self.assertFalse(over_budget(99, 100))
        self.assertTrue(over_budget(100, 100))
        self.assertFalse(over_budget(100, 0))

    def test_days_outside_the_range_are_rejected(self) -> None:
        from app.service.ai.usage import _days

        with self.assertRaises(AppError):
            _days(0)
        with self.assertRaises(AppError):
            _days(91)
