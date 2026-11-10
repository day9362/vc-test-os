import unittest

from app.service.reports.report_service import _main_fail_text


class MainFailTextTests(unittest.TestCase):
    def test_lists_every_item_above_forty_percent_with_its_share(self) -> None:
        text, count = _main_fail_text({"Temp_T1-T6": 1200, "Temp_T1-T5": 1189, "Temp_T1-T4": 97, "室温": 262}, 1200)
        self.assertEqual(text, "Temp_T1-T6 100%、Temp_T1-T5 99.1%")
        self.assertEqual(count, 1200)

    def test_keeps_the_largest_item_when_none_pass_forty_percent(self) -> None:
        text, count = _main_fail_text({"Temp_T1-T4": 30, "室温": 20}, 100)
        self.assertEqual(text, "Temp_T1-T4 30%")
        self.assertEqual(count, 30)

    def test_forty_percent_itself_is_left_out_when_another_item_is_higher(self) -> None:
        text, _count = _main_fail_text({"Temp_T1-T6": 50, "Temp_T1-T4": 40}, 100)
        self.assertEqual(text, "Temp_T1-T6 50%")


if __name__ == "__main__":
    unittest.main()
