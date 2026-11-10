import asyncio
import unittest

from app.core.errors import AppError
from app.service.reports.narrative import SummaryRun, chat_completions_url, fill_template, grounded_lines, polish_summary_lines, render_cross, render_single, tool_page, tool_place, tool_process, tool_results, unify_words


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

    def test_unit_does_not_split_a_decimal_that_already_has_one(self) -> None:
        lines = polish_summary_lines(["Temp_T1-T9，最大值4.21℃贴近上限4.8℃。"])
        self.assertEqual(lines, ["Temp_T1-T9，最大值4.21℃贴近上限4.8℃。"])

    def test_slot_sentence_does_not_put_the_unit_on_the_slot(self) -> None:
        lines = polish_summary_lines(["M01#1槽位Temp_T0-T1极差0.786更大，其余槽位片数不足。"])
        self.assertEqual(lines, ["M01 槽1 的 Temp_T0-T1 极差0.786 ℃。其余槽位片数不足。"])

    def test_does_not_treat_digits_inside_a_batch_id_as_new_numbers(self) -> None:
        text = '{"lines": ["批次 B-tb172-9a60ea3a 共 1 个。"]}'
        self.assertEqual(grounded_lines(text, PAYLOAD), ["批次 B-tb172-9a60ea3a 共 1 个。"])

    def test_results_query_stays_on_one_item(self) -> None:
        rows = []
        for index in range(3):
            rows.append({"run_id": f"f{index}", "serial": f"F{index}", "batch_id": "B1", "machine_id": "M1", "slot_name": "M1#1", "item": "Temp_T1-T2", "key": "delta_t1_t2", "value": 6.0, "low": 0, "high": 4.8, "passed": False})
            rows.append({"run_id": f"f{index}", "serial": f"F{index}", "batch_id": "B1", "machine_id": "M1", "slot_name": "M1#1", "item": "Temp_T0-T1", "key": "delta_t0_t1", "value": 1.0, "low": 0, "high": 3, "passed": False})
        rows.append({"run_id": "p1", "serial": "P1", "batch_id": "B1", "machine_id": "M2", "slot_name": "M2#2", "item": "Temp_T1-T2", "key": "delta_t1_t2", "value": 1.2, "low": 0, "high": 4.8, "passed": True})
        payload = {"batches": [{"name": "B1", "items": [{"item": "Temp_T1-T2", "n": 4, "mean": 4.8, "minimum": 1.2, "maximum": 6, "range": 4.8, "low": 0, "high": 4.8, "high_fail": 3, "low_fail": 0}]}]}
        result = tool_results(payload, rows, "T1-T2")
        self.assertEqual(result["item"], "Temp_T1-T2")
        block = result["batches"][0]
        self.assertEqual(block["over_count"], 3)
        self.assertTrue(all(row["serial"].startswith("F") for row in block["over"]))
        self.assertEqual([row["serial"] for row in block["pass_sample"]], ["P1"])
        self.assertNotIn("Temp_T0-T1", str(result))

    def test_a_failed_product_inside_the_limit_is_not_an_item_failure(self) -> None:
        rows = [{"run_id": "f0", "serial": "F0", "batch_id": "B1", "machine_id": "M1", "slot_name": "M1#1", "item": "Temp_T0-T1", "key": "delta_t0_t1", "value": 2.0, "low": 0, "high": 3.4, "passed": False}]
        payload = {"batches": [{"name": "B1", "items": [{"item": "Temp_T0-T1", "n": 1, "mean": 2, "minimum": 2, "maximum": 2, "range": 0, "low": 0, "high": 3.4, "high_fail": 0, "low_fail": 0}]}]}
        block = tool_results(payload, rows, "Temp_T0-T1")["batches"][0]
        self.assertEqual(block["over_count"], 0)
        self.assertEqual(block["over"], [])
        self.assertEqual(block["high_fail"], 0)

    def test_process_without_a_stored_curve_says_so(self) -> None:
        rows = [{"run_id": "f0", "serial": "F0", "batch_id": "B1", "machine_id": "M1", "slot_name": "M1#1", "item": "Temp_T1-T2", "key": "delta_t1_t2", "value": 6.0, "low": 0, "high": 4.8, "passed": False}]
        result = asyncio.run(tool_process(None, rows, "Temp_T1-T2", []))
        self.assertIn("没有过程曲线", result["note"])
        self.assertEqual(result["serials"], ["F0"])

    def test_page_gives_yield_and_range(self) -> None:
        rows = [
            {"run_id": "f0", "serial": "F0", "batch_id": "B1", "machine_id": "M1", "slot_name": "M1#1", "item": "Temp_T1-T2", "key": "delta_t1_t2", "value": 6.0, "low": 0, "high": 4.8, "passed": False},
            {"run_id": "p1", "serial": "P1", "batch_id": "B1", "machine_id": "M2", "slot_name": "M2#2", "item": "Temp_T1-T2", "key": "delta_t1_t2", "value": 1.2, "low": 0, "high": 4.8, "passed": True},
        ]
        payload = {"batches": [{"name": "B1", "items": [{"item": "Temp_T1-T2", "n": 2, "mean": 3.6, "minimum": 1.2, "maximum": 6, "range": 4.8, "low": 0, "high": 4.8, "high_fail": 1, "low_fail": 0}]}]}
        page = tool_page(payload, rows)
        block = page["batches"][0]
        self.assertEqual(block["tested"], 2)
        self.assertEqual(block["failed"], 1)
        self.assertEqual(block["yield_rate"], 50)
        self.assertEqual(block["items"][0]["range"], 4.8)

    def test_place_counts_fails_by_machine_and_slot(self) -> None:
        rows = [
            {"run_id": "a", "serial": "A", "batch_id": "B1", "machine_id": "M1", "slot_name": "M1#1", "item": "Temp_T1-T5", "value": 6, "low": 0, "high": 4.8, "passed": False},
            {"run_id": "b", "serial": "B", "batch_id": "B1", "machine_id": "M1", "slot_name": "M1#2", "item": "Temp_T1-T5", "value": 1, "low": 0, "high": 4.8, "passed": True},
            {"run_id": "c", "serial": "C", "batch_id": "B1", "machine_id": "M2", "slot_name": "M2#1", "item": "Temp_T1-T5", "value": 1, "low": 0, "high": 4.8, "passed": True},
        ]
        result = tool_place(rows, "Temp_T1-T5")
        machines = {row["name"]: row for row in result["batches"][0]["machines"]}
        slots = {row["name"]: row for row in result["batches"][0]["slots"]}
        self.assertEqual(machines["M1"]["high_fail"], 1)
        self.assertEqual(machines["M1"]["n"], 2)
        self.assertEqual(machines["M2"]["high_fail"], 0)
        self.assertEqual(slots["M1#1"]["high_fail"], 1)
        self.assertEqual(slots["M1#2"]["high_fail"], 0)
        self.assertEqual(machines["M1"]["minimum"], 1)
        self.assertEqual(machines["M1"]["maximum"], 6)

    def test_single_batch_conclusion_waits_for_place(self) -> None:
        rows = [{"run_id": "f0", "serial": "F0", "batch_id": "B1", "machine_id": "M1", "slot_name": "M1#1", "item": "Temp_T1-T2", "key": "delta_t1_t2", "value": 6.0, "low": 0, "high": 4.8, "passed": False}]
        payload = {"batches": [{"name": "B1", "items": [{"item": "Temp_T1-T2", "n": 1, "mean": 6, "minimum": 6, "maximum": 6, "range": 0, "low": 0, "high": 4.8, "high_fail": 1, "low_fail": 0}]}]}

        async def walk():
            run = SummaryRun(payload, "single", rows, None)
            early = await run.turn({"exposed": ["超了"], "risk": []})
            blocked = await run.turn({"tool": "results", "item": "Temp_T1-T2"})
            await run.turn({"tool": "place", "item": "Temp_T1-T2"})
            again = await run.turn({"tool": "results", "item": "Temp_T1-T2"})
            done = await run.turn({"exposed": ["超了"], "risk": []})
            return run.opening(), early, blocked, again, done

        opening, early, blocked, again, done = asyncio.run(walk())
        self.assertIn("yield_rate", opening)
        self.assertEqual(early["items"], ["Temp_T1-T2"])
        self.assertEqual(blocked["items"], ["Temp_T1-T2"])
        self.assertIn("写结论", again["error"])
        self.assertTrue(done["done"])

    def test_single_conclusion_uses_the_three_patterns(self) -> None:
        page = {"batches": [{"batch": "B1", "items": [
            {"item": "Temp_T1-T6", "n": 2, "minimum": 4.9, "maximum": 4.9, "range": 0, "low": 0, "high": 4.8, "high_fail": 2, "low_fail": 0},
            {"item": "Temp_T1-T4", "n": 3, "minimum": 4.1, "maximum": 4.9, "range": 0.8, "low": 0, "high": 4.8, "high_fail": 2, "low_fail": 0},
            {"item": "室温", "n": 3, "minimum": 25, "maximum": 27.2, "range": 2.2, "low": 23, "high": 27, "high_fail": 2, "low_fail": 0},
            {"item": "Temp_T1-T2", "n": 1, "minimum": 4.6, "maximum": 4.7, "range": 0.3, "low": 0, "high": 4.8, "high_fail": 0, "low_fail": 0},
        ]}]}
        run = SummaryRun({"batches": []}, "single", [], None)
        run.results = [
            {"tool": "page", "result": page},
            {"tool": "place", "result": {"item": "Temp_T1-T6", "batches": [{"batch": "B1", "machines": [{"name": "M01", "n": 1, "high_fail": 1, "low_fail": 0}, {"name": "M02", "n": 1, "high_fail": 1, "low_fail": 0}], "slots": [{"name": "M01#1", "n": 1, "high_fail": 1, "low_fail": 0}, {"name": "M02#1", "n": 1, "high_fail": 1, "low_fail": 0}]}]}},
            {"tool": "place", "result": {"item": "Temp_T1-T4", "batches": [{"batch": "B1", "machines": [{"name": "M03", "n": 2, "high_fail": 2, "low_fail": 0}, {"name": "M01", "n": 1, "high_fail": 0, "low_fail": 0}], "slots": [{"name": "M03#1", "n": 1, "high_fail": 1, "low_fail": 0}, {"name": "M03#2", "n": 1, "high_fail": 1, "low_fail": 0}, {"name": "M01#1", "n": 1, "high_fail": 0, "low_fail": 0}]}]}},
            {"tool": "place", "result": {"item": "室温", "batches": [{"batch": "B1", "machines": [{"name": "M01", "n": 1, "high_fail": 0, "low_fail": 0}, {"name": "M02", "n": 1, "high_fail": 1, "low_fail": 0}, {"name": "M03", "n": 1, "high_fail": 1, "low_fail": 0}], "slots": [{"name": "M01#1", "n": 1, "high_fail": 0, "low_fail": 0}, {"name": "M02#2", "n": 1, "high_fail": 1, "low_fail": 0}, {"name": "M03#1", "n": 1, "high_fail": 1, "low_fail": 0}]}]}},
        ]
        lines = grounded_lines(render_single(run), {"results": run.results})
        text = "\n".join(lines)
        self.assertIn("Temp_T1-T6 是整批一起过限，怀疑产品问题。", text)
        self.assertIn("Temp_T1-T4 集中在 M03，怀疑这台机。", text)
        self.assertIn("室温 超限集中在 M02#2（1 片）、M03#1（1 片），怀疑这些槽位。", text)
        self.assertIn("Temp_T1-T2：最大值 4.7 ℃ 贴近上限 4.8 ℃，离上限的距离小于这一项的极差，所以写成贴近上限。", text)
        self.assertIn("排除只是少数片子超出去。", text)
        self.assertIn("排除整批产品问题。", text)
        self.assertIn("M03#1（1 片）#2（1 片）", text)

    def test_cross_compares_one_item_across_batches(self) -> None:
        page = {"batches": [
            {"batch": "B-A", "tested": 4, "yield_rate": 0, "items": [
                {"item": "Temp_T1-T6", "n": 4, "minimum": 4.9, "maximum": 5.1, "mean": 4.99, "range": 0.2, "low": 0, "high": 4.8, "high_fail": 4, "low_fail": 0},
                {"item": "Temp_T1-T4", "n": 4, "minimum": 4.5, "maximum": 5.0, "mean": 4.78, "range": 0.5, "low": 0, "high": 4.8, "high_fail": 2, "low_fail": 0},
                {"item": "室温", "n": 4, "minimum": 25, "maximum": 26.5, "mean": 25.8, "range": 1.5, "low": 23, "high": 27, "high_fail": 0, "low_fail": 0},
            ]},
            {"batch": "B-B", "tested": 4, "yield_rate": 0, "items": [
                {"item": "Temp_T1-T6", "n": 4, "minimum": 4.85, "maximum": 5.05, "mean": 4.96, "range": 0.2, "low": 0, "high": 4.8, "high_fail": 4, "low_fail": 0},
                {"item": "Temp_T1-T4", "n": 4, "minimum": 4.2, "maximum": 4.5, "mean": 4.4, "range": 0.3, "low": 0, "high": 4.8, "high_fail": 0, "low_fail": 0},
                {"item": "室温", "n": 4, "minimum": 25, "maximum": 27.8, "mean": 26.4, "range": 2.8, "low": 23, "high": 27, "high_fail": 3, "low_fail": 0},
            ]},
        ]}
        run = SummaryRun({"batches": []}, "cross", [], None)
        run.results = [
            {"tool": "page", "result": page},
            {"tool": "place", "result": {"item": "Temp_T1-T6", "batches": [
                {"batch": "B-A", "machines": [{"name": "M01", "n": 2, "high_fail": 2, "low_fail": 0}, {"name": "M02", "n": 2, "high_fail": 2, "low_fail": 0}], "slots": []},
                {"batch": "B-B", "machines": [{"name": "M01", "n": 2, "high_fail": 2, "low_fail": 0}, {"name": "M03", "n": 2, "high_fail": 2, "low_fail": 0}], "slots": []},
            ]}},
            {"tool": "place", "result": {"item": "Temp_T1-T4", "batches": [
                {"batch": "B-A", "machines": [{"name": "M02", "n": 2, "high_fail": 2, "low_fail": 0}, {"name": "M01", "n": 2, "high_fail": 0, "low_fail": 0}], "slots": [{"name": "M02#1", "n": 1, "high_fail": 1, "low_fail": 0}, {"name": "M02#2", "n": 1, "high_fail": 1, "low_fail": 0}]},
                {"batch": "B-B", "machines": [{"name": "M01", "n": 2, "high_fail": 0, "low_fail": 0}, {"name": "M03", "n": 2, "high_fail": 0, "low_fail": 0}], "slots": []},
            ]}},
            {"tool": "place", "result": {"item": "室温", "batches": [
                {"batch": "B-A", "machines": [{"name": "M01", "n": 2, "high_fail": 0, "low_fail": 0}], "slots": [{"name": "M01#2", "n": 2, "high_fail": 0, "low_fail": 0}]},
                {"batch": "B-B", "machines": [{"name": "M03", "n": 2, "high_fail": 2, "low_fail": 0}, {"name": "M01", "n": 2, "high_fail": 1, "low_fail": 0}], "slots": [{"name": "M03#1", "n": 2, "high_fail": 2, "low_fail": 0}, {"name": "M01#2", "n": 2, "high_fail": 1, "low_fail": 0}, {"name": "M03#2", "n": 2, "high_fail": 0, "low_fail": 0}]},
            ]}},
        ]
        lines = grounded_lines(render_cross(run), {"results": run.results})
        text = "\n".join(lines)
        self.assertIn("按同一项对齐。", text)
        self.assertIn("Temp_T1-T6 两批都是整批一起过限，怀疑产品问题。", text)
        self.assertIn("换了机台仍然整批抬高，排除某一台机。", text)
        self.assertIn("这个差距小于各自极差。", text)
        self.assertIn("Temp_T1-T4 只出在批次一的 M02，怀疑这台机。", text)
        self.assertIn("批次二没有 M02。", text)
        self.assertIn("室温 只出在批次二的 M01#2（1 片）、M03#1（2 片），怀疑这些槽位。", text)
        self.assertIn("排除整批只是被一起平移。", text)
        self.assertLess(text.find("Temp_T1-T4"), text.find("Temp_T1-T6"))
        self.assertNotIn("更好", text)

    def test_template_queries_every_fail_item_without_the_model(self) -> None:
        rows = [
            {"run_id": "a", "serial": "A", "batch_id": "B1", "machine_id": "M01", "slot_name": "M01#1", "item": "Temp_T1-T4", "value": 5.1, "low": 0, "high": 4.8, "passed": False},
            {"run_id": "b", "serial": "B", "batch_id": "B1", "machine_id": "M02", "slot_name": "M02#1", "item": "Temp_T1-T6", "value": 5.2, "low": 0, "high": 4.8, "passed": False},
        ]
        payload = {"batches": [{"name": "B1", "items": [
            {"item": "Temp_T1-T4", "n": 1, "mean": 5.1, "minimum": 5.1, "maximum": 5.1, "range": 0, "low": 0, "high": 4.8, "high_fail": 1, "low_fail": 0},
            {"item": "Temp_T1-T6", "n": 1, "mean": 5.2, "minimum": 5.2, "maximum": 5.2, "range": 0, "low": 0, "high": 4.8, "high_fail": 1, "low_fail": 0},
        ]}]}

        async def walk():
            run = SummaryRun(payload, "single", rows, None)
            await fill_template(run)
            return run.placed, grounded_lines(render_single(run), {"results": run.results})

        placed, lines = asyncio.run(walk())
        self.assertEqual(placed, {"Temp_T1-T4", "Temp_T1-T6"})
        self.assertIn("怀疑产品问题。", "\n".join(lines))

    def test_single_mode_keeps_each_batch_in_its_own_section(self) -> None:
        page = {"batches": [
            {"batch": "B-A", "tested": 2, "yield_rate": 0, "items": [
                {"item": "power_w", "n": 2, "mean": 3.5, "minimum": 3.5, "maximum": 3.501, "range": 0.001, "low": 3.4, "high": 3.6, "high_fail": 0, "low_fail": 0},
            ]},
            {"batch": "B-B", "tested": 2, "yield_rate": 0, "items": [
                {"item": "Temp_T1-T2", "n": 2, "mean": 3.9, "minimum": 3.8, "maximum": 3.972, "range": 0.172, "low": 0, "high": 4, "high_fail": 0, "low_fail": 0},
            ]},
        ]}
        run = SummaryRun({"batches": []}, "single", [], None)
        run.results = [{"tool": "page", "result": page}]
        lines = grounded_lines(render_single(run), {"results": run.results})
        first = lines.index("已暴露的卡限项")
        second = lines.index("已暴露的卡限项", first + 1)
        risk_a = lines.index("潜在危险项")
        risk_b = lines.index("潜在危险项", risk_a + 1)
        self.assertLess(risk_a, second)
        self.assertLess(second, risk_b)
        self.assertIn("B-A", "\n".join(lines[first:second]))
        self.assertIn("B-B", "\n".join(lines[second:]))
        self.assertIn("power_w", "\n".join(lines[risk_a:second]))
        self.assertIn("Temp_T1-T2", "\n".join(lines[risk_b:]))
