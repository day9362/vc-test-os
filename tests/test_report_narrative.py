import unittest

from app.core.errors import AppError
from app.service.reports.narrative import chat_completions_url, grounded_lines


PAYLOAD = {
    "batch_count": 1,
    "batches": [{"batch_id": "B-tb172-9a60ea3a", "tested": 120, "passed": 100, "failed": 20, "yield_rate": 83.33}],
    "summary": {"tested": 120, "yield_rate": 83.33, "rc_mean": 4.909},
}


class NarrativeTests(unittest.TestCase):
    def test_chat_url_drops_anthropic_suffix(self) -> None:
        self.assertEqual(chat_completions_url("https://api.deepseek.com/anthropic"), "https://api.deepseek.com/chat/completions")

    def test_keeps_numbers_copied_from_the_report(self) -> None:
        text = '{"lines": ["批次 B-tb172-9a60ea3a 测了 120 片，良率 83.33%，Rc 均值 4.909。"]}'
        self.assertEqual(len(grounded_lines(text, PAYLOAD)), 1)

    def test_drops_a_number_the_report_does_not_have(self) -> None:
        text = '{"lines": ["不合格大约 99 片。"]}'
        with self.assertRaises(AppError) as caught:
            grounded_lines(text, PAYLOAD)
        self.assertEqual(caught.exception.message, "总结里的数字和报告对不上")

    def test_adds_chinese_after_english_field_names(self) -> None:
        text = '{"lines": ["tested 120, passed 100, failed 20, yield_rate 83.33, rc_mean 4.909。"]}'
        line = grounded_lines(text, PAYLOAD)[0]
        self.assertIn("tested（测试数）", line)
        self.assertIn("passed（合格）", line)
        self.assertIn("failed（不合格）", line)
        self.assertIn("yield_rate（良率）", line)
        self.assertIn("rc_mean（Rc 均值）", line)

    def test_keeps_a_chinese_note_the_model_already_wrote(self) -> None:
        text = '{"lines": ["tested（测试数） 120，yield_rate 83.33。"]}'
        line = grounded_lines(text, PAYLOAD)[0]
        self.assertIn("tested（测试数） 120", line)
        self.assertNotIn("tested（测试数）（测试数）", line)
        self.assertIn("yield_rate（良率）", line)

    def test_does_not_treat_digits_inside_a_batch_id_as_new_numbers(self) -> None:
        text = '{"lines": ["批次 B-tb172-9a60ea3a 共 1 个。"]}'
        self.assertEqual(grounded_lines(text, PAYLOAD), ["批次 B-tb172-9a60ea3a 共 1 个。"])
