import unittest

from app.core.errors import AppError
from app.service.reports.narrative import chat_completions_url, grounded_lines, polish_summary_lines, unify_words


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

    def test_rewrites_limit_words_to_the_same_set(self) -> None:
        self.assertEqual(unify_words("5 片样品偏高限，高限 5.0，低限 0，超出上限，各5片上限不合格。"), "5 片偏上限，上限 5.0，下限 0，超上限，各5片超上限。")
        self.assertEqual(unify_words("最大 6.370，最小 5.584，最大值已有。"), "最大值 6.370，最小值 5.584，最大值已有。")

    def test_orders_temperature_lines_and_adds_unit(self) -> None:
        lines = polish_summary_lines([
            "测了 5 片。",
            "Temp_T1-T4均值5.715，极差0.242，上限3.0，超上限5片。",
            "Temp_T1-T5均值5.787，极差0.309，上限2.0，超上限5片。",
            "Temp_T1-T2均值3.525，极差0.382，上限4.0，超上限0片。",
            "Temp_T0-T1均值5.973，极差0.786，上限5.0，超上限5片。",
        ])
        self.assertEqual(lines[0], "测了 5 片。")
        self.assertTrue(lines[1].startswith("Temp_T0-T1均值5.973 ℃"))
        self.assertTrue(lines[2].startswith("Temp_T1-T2均值3.525 ℃"))
        self.assertTrue(lines[3].startswith("Temp_T1-T4均值5.715 ℃"))
        self.assertTrue(lines[4].startswith("Temp_T1-T5均值5.787 ℃"))
        self.assertIn("超上限5片", lines[1])

    def test_slot_sentence_does_not_put_the_unit_on_the_slot(self) -> None:
        lines = polish_summary_lines(["M01#1槽位Temp_T0-T1极差0.786更大，其余槽位片数不足。"])
        self.assertEqual(lines, ["M01 槽1 的 Temp_T0-T1 极差0.786 ℃。其余槽位片数不足。"])

    def test_does_not_treat_digits_inside_a_batch_id_as_new_numbers(self) -> None:
        text = '{"lines": ["批次 B-tb172-9a60ea3a 共 1 个。"]}'
        self.assertEqual(grounded_lines(text, PAYLOAD), ["批次 B-tb172-9a60ea3a 共 1 个。"])
