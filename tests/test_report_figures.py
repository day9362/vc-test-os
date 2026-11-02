import unittest

from app.core.errors import AppError
from app.service.reports.chart_spec import compile_stored
from app.service.reports.figure_scope import asked_group, prepare_records, uses_fixed_charts
from app.service.reports.pdf import chart_bars
from app.models.orm.run import RunOrm
from app.service.reports.figures import limit_deltas
from app.service.reports.presets import run_preset, test_rows
from app.service.reports.sandbox import reject_code, sanitize_option
from app.service.reports.stats import student_t_sf


class FigureSandboxTests(unittest.TestCase):
    def test_rejects_os_and_network_imports(self) -> None:
        self.assertIn("os", reject_code("import os\ndef analyze(runs):\n    return {}"))
        self.assertIn("subprocess", reject_code("import subprocess\ndef analyze(runs):\n    return {}"))
        self.assertEqual(reject_code("def analyze(runs):\n    return {'title': 'Rc'}"), "")

    def test_keeps_a_plain_chart_option(self) -> None:
        option = sanitize_option({"xAxis": {"type": "category", "data": ["M01"]}, "series": [{"type": "bar", "data": [1]}]})
        self.assertEqual(option["series"][0]["data"], [1])

    def test_rejects_a_function_inside_the_option(self) -> None:
        with self.assertRaises(AppError):
            sanitize_option({"series": [{"type": "bar", "data": [1], "label": {"formatter": "function (v) { return v }" }}]})


class ChartSpecTests(unittest.TestCase):
    def test_slot_scatter_lists_only_slots_that_were_used(self) -> None:
        panels, error = compile_stored({
            "panels": [{
                "type": "scatter",
                "x_name": "slot_index",
                "y_name": "温差(℃)",
                "series": [{"name": "Temp_T0-T1", "data": [[1, 6.37], [1, 5.584], [2, 5.693], [4, 6.147]]}],
            }],
        })
        self.assertEqual(error, "")
        axis = panels[0]["option"]["xAxis"]
        self.assertEqual(axis["type"], "category")
        self.assertEqual(axis["data"], ["槽1", "槽2", "槽4"])

    def test_two_delta_scatter_stays_numeric(self) -> None:
        panels, error = compile_stored({
            "panels": [{
                "type": "scatter",
                "x_name": "Temp_T0-T1",
                "y_name": "Temp_T1-T2",
                "series": [{"name": "片", "data": [[5.973, 3.525], [6.1, 3.4]]}],
            }],
        })
        self.assertEqual(error, "")
        self.assertEqual(panels[0]["option"]["xAxis"]["type"], "value")

    def test_pareto_sorts_and_adds_the_cumulative_share(self) -> None:
        panels, error = compile_stored({
            "panels": [{
                "type": "pareto",
                "categories": ["温差", "Rc"],
                "series": [{"name": "次数", "data": [1, 3]}],
            }],
        })
        self.assertEqual(error, "")
        option = panels[0]["option"]
        self.assertEqual(option["xAxis"]["data"], ["Rc", "温差"])
        self.assertEqual(option["series"][0]["data"], [3, 1])
        self.assertEqual(option["series"][1]["data"], [75.0, 100.0])
        self.assertEqual(option["yAxis"][1]["max"], 100)

    def test_keeps_a_legacy_echarts_option(self) -> None:
        panels, error = compile_stored({"echarts_option": {"xAxis": {"type": "category", "data": ["a"]}, "series": [{"type": "bar", "data": [1]}]}})
        self.assertEqual(error, "")
        self.assertEqual(panels[0]["option"]["series"][0]["data"], [1])

    def test_two_sided_t_at_the_five_percent_point(self) -> None:
        self.assertAlmostEqual(student_t_sf(2.228, 10), 0.05, delta=0.002)
        self.assertAlmostEqual(student_t_sf(0, 10), 1, delta=1e-9)


def _delta(item: str, value: float, high: float = 4) -> dict:
    return {"item": item, "value": value, "low": 0, "high": high}


class FigureScopeTests(unittest.TestCase):
    def test_a_general_delta_request_uses_every_limited_item(self) -> None:
        prepared = prepare_records("温差分析一下这批产品", [_scope_record()])
        self.assertEqual(prepared.summary["rows"][0][0], "Temp_T0-T1")
        self.assertEqual(prepared.summary["rows"][1][0], "Temp_T1-T2")
        self.assertIn("本批全部槽位", prepared.summary["scope"])
        self.assertEqual(prepared.summary["rows"][0][2], "5.973 ℃")
        self.assertEqual(prepared.notes, [])
        chart = run_preset("overview", prepared.records)
        self.assertEqual([panel["title"] for panel in chart["panels"]], ["温差分布", "超限片数"])
        self.assertEqual(chart["panels"][1]["series"][0]["data"], [1, 0])

    def test_compact_item_names_do_not_pull_in_every_delta(self) -> None:
        prepared = prepare_records("TempT0-T1和TempT1-T3两项温差", [_scope_record()])
        self.assertEqual([row[0] for row in prepared.summary["rows"]], ["Temp_T0-T1"])
        self.assertIn("Temp_T1-T3 没有卡限，未列入", prepared.notes)

    def test_a_named_slot_and_an_unlimited_item_are_separated(self) -> None:
        prepared = prepare_records("看一下 M01 槽1 和槽9 的 Temp_T0-T1、Temp_T1-T3", [_scope_record()])
        self.assertEqual([item["item"] for item in prepared.records[0]["deltas"]], ["Temp_T0-T1", "Temp_T1-T3"])
        self.assertEqual([row[0] for row in prepared.summary["rows"]], ["Temp_T0-T1"])
        self.assertIn("槽9 没有测过，未列入", prepared.notes)
        self.assertIn("Temp_T1-T3 没有卡限，未列入", prepared.notes)
        self.assertIn("M01 槽1", prepared.summary["scope"])

    def test_named_slots_keep_limited_deltas_and_ambient(self) -> None:
        records = [
            _scope_record(),
            {**_scope_record(), "slot_index": 2, "serial_number": "0002", "ambient": 25.496},
            {**_scope_record(), "slot_index": 3, "serial_number": "0003", "ambient": 25.141},
        ]
        records[0]["ambient"] = 25.622
        prepared = prepare_records("分析一下M01的槽1和槽2", records)
        self.assertEqual([record["slot_index"] for record in prepared.records], [1, 2])
        self.assertNotIn("室温", [row[0] for row in prepared.summary["rows"]])
        asked = prepare_records("分析一下M01的槽1和槽2的室温", records)
        self.assertEqual(asked.summary["rows"][-1][0], "室温")
        self.assertEqual(asked.summary["rows"][-1][1], "2 片")
        self.assertIn("M01 槽1", prepared.summary["scope"])
        self.assertNotIn("槽3", prepared.summary["scope"])
        titles = [panel["title"] for panel in run_preset("overview", prepared.records)["panels"]]
        self.assertNotIn("室温", titles)
        self.assertIn("Temp_T0-T1 槽位均值", titles)
        self.assertIn("Temp_T1-T2 槽位均值", titles)

    def test_a_slot_request_compares_every_limited_item_by_slot(self) -> None:
        self.assertEqual(asked_group("按机台槽位比较比较一下卡limit项的情况"), "slot")
        self.assertEqual(asked_group("温差分析一下这批产品"), "")
        self.assertTrue(uses_fixed_charts("按机台槽位比较比较一下卡limit项的情况"))
        records = [
            {"machine_id": "M01", "slot_index": slot, "deltas": [
                {"item": "Temp_T0-T1", "value": 6.0, "low": 0, "high": 5, "limited": True, "order": 0},
                {"item": "Temp_T1-T2", "value": 3.5, "low": 0, "high": 4, "limited": True, "order": 1},
            ]}
            for slot in (1, 2)
        ]
        panels = run_preset("grouped", records, "slot")["panels"]
        self.assertEqual([panel["title"] for panel in panels], ["Temp_T0-T1", "Temp_T1-T2"])
        self.assertEqual(panels[0]["x_name"], "槽位")
        self.assertEqual(panels[0]["categories"], ["M01 槽1", "M01 槽2"])
        self.assertEqual(panels[1]["categories"], ["M01 槽1", "M01 槽2"])

    def test_temperature_charts_keep_delta_items_and_list_each_slot_mean(self) -> None:
        records = []
        for slot in (1, 2):
            records.append({
                "machine_id": "M01",
                "slot_index": slot,
                "ambient": 25.0,
                "deltas": [
                    {"item": "Temp_T0-T1", "value": 6.0, "low": 0, "high": 5, "limited": True, "order": 0},
                    {"item": "Temp_T1-T2", "value": 3.5, "low": 0, "high": 4, "limited": True, "order": 1},
                    {"item": "power_w", "value": 2.5, "low": 2.4, "high": 2.6, "limited": True, "order": 2},
                    {"item": "室温", "value": 25.0, "low": 23, "high": 27, "limited": True, "order": 3},
                ],
            })
        panels = run_preset("overview", records)["panels"]
        distribution = panels[0]
        counts = panels[1]
        self.assertEqual(distribution["categories"], ["Temp_T0-T1", "Temp_T1-T2"])
        self.assertEqual(counts["categories"], ["Temp_T0-T1", "Temp_T1-T2"])
        self.assertEqual([panel["title"] for panel in panels[2:]], ["Temp_T0-T1 槽位均值", "Temp_T1-T2 槽位均值"])
        self.assertEqual(run_preset("overview", records, "", True)["panels"][-1]["title"], "室温")

    def test_an_all_zero_chart_is_rejected(self) -> None:
        from app.service.reports.figures import _values_are_all_zero

        self.assertTrue(_values_are_all_zero([{"option": {"series": [{"data": [0, 0]}]}}]))
        self.assertFalse(_values_are_all_zero([{"option": {"series": [{"data": [5.973]}]}}]))


def _scope_record() -> dict:
    return {
        "machine_id": "M01",
        "slot_index": 1,
        "serial_number": "0001",
        "passed": False,
        "deltas": [
            {"item": "Temp_T0-T1", "value": 5.973, "low": 0, "high": 5, "limited": True},
            {"item": "Temp_T1-T2", "value": 3.525, "low": 0, "high": 4, "limited": True},
        ],
        "measured": [
            {"item": "Temp_T0-T1", "value": 5.973},
            {"item": "Temp_T1-T2", "value": 3.525},
            {"item": "Temp_T1-T3", "value": 4.93},
        ],
    }


class PresetFigureTests(unittest.TestCase):
    def test_limit_deltas_keep_spec_deltas_and_drop_thermal_resistance(self) -> None:
        row = RunOrm(
            run_id="r", machine_id="M1", slot_index=1, plan_id="P", plan_version=1,
            status="COMPLETED", ended_at=1,
            result={"deltas": {"Rc": 3.2, "Temp_T0-T1": 2.2, "Temp_T1-T2": 1.1}},
        )
        spec = {
            "delta_t0_t1": ("Temp_T0-T1", 0, 2.8),
            "delta_t1_t2": ("Temp_T1-T2", 0, 4),
            "thermal_resistance": ("Rc", None, 5),
        }
        self.assertEqual([item["item"] for item in limit_deltas(row, spec)], ["Temp_T0-T1", "Temp_T1-T2"])

    def test_delta_order_follows_the_plan_not_the_name(self) -> None:
        row = RunOrm(
            run_id="r", machine_id="M1", slot_index=1, plan_id="P", plan_version=1,
            status="COMPLETED", ended_at=1,
            result={"deltas": {"Temp_T0-T1": 2.2, "Temp_T1-T4": 1.1}},
        )
        spec = {
            "delta_t1_t4": ("Temp_T1-T4", 0, 3),
            "delta_t0_t1": ("Temp_T0-T1", 0, 5),
        }
        self.assertEqual([item["item"] for item in limit_deltas(row, spec)], ["Temp_T1-T4", "Temp_T0-T1"])
        records = [{"machine_id": "M1", "slot_index": 1, "deltas": limit_deltas(row, spec)}]
        self.assertEqual([panel["title"] for panel in run_preset("slot_rc", records)["panels"]], ["Temp_T1-T4", "Temp_T0-T1"])

    def test_pareto_counts_deltas_over_the_limit(self) -> None:
        records = [
            {"deltas": [_delta("Temp_T1-T2", 5), _delta("Temp_T0-T1", 1)], "fail_items": "Rc"},
            {"deltas": [_delta("Temp_T1-T2", 6)]},
            {"deltas": [_delta("Temp_T0-T1", 3, high=2)]},
        ]
        panels, error = compile_stored(run_preset("pareto", records))
        self.assertEqual(error, "")
        self.assertEqual(panels[0]["option"]["xAxis"]["data"], ["Temp_T0-T1", "Temp_T1-T2"])
        self.assertEqual(panels[0]["option"]["series"][0]["data"], [1, 2])
        self.assertEqual(panels[0]["option"]["series"][1]["name"], "超下限")
        self.assertEqual(len(panels[0]["option"]["series"]), 2)

    def test_a_requested_group_comparison_is_computed_from_the_rows(self) -> None:
        records = [{"batch_id": "A", "deltas": [_delta("Temp_T0-T1", value)]} for value in (1, 1.1, 0.9)]
        records += [{"batch_id": "B", "deltas": [_delta("Temp_T0-T1", value)]} for value in (2, 2.2, 1.8)]
        rows = test_rows(records, [{"y": "Temp_T0-T1", "by": "batch_id", "left": "A", "right": "B"}])
        self.assertEqual(rows[-1], ["Welch t p 值", "0.005"])

    def test_compare_adds_a_welch_p_value(self) -> None:
        records = []
        for batch, values in (("A", [1, 1.1, 0.9, 1.05]), ("B", [3, 3.2, 2.8, 3.1])):
            for value in values:
                records.append({"batch_id": batch, "machine_id": "M1", "deltas": [_delta("Temp_T0-T1", value)]})
        panel = run_preset("compare", records)["panels"][0]
        self.assertEqual(panel["categories"], ["A", "B"])
        self.assertEqual(panel["y_name"], "℃")
        self.assertEqual(panel["marks"][0]["name"], "上限")
        self.assertEqual(run_preset("compare", records)["results"], [])

    def test_scatter_reports_correlation(self) -> None:
        records = [{
            "deltas": [_delta("Temp_T0-T1", float(index), 10), _delta("Temp_T1-T2", float(index) * 2, 10)],
        } for index in range(1, 6)]
        panel = run_preset("scatter", records)["panels"][0]
        self.assertEqual(panel["type"], "boxplot")
        self.assertEqual(panel["categories"], ["Temp_T0-T1", "Temp_T1-T2"])
        self.assertEqual(run_preset("scatter", records)["results"], [])

    def test_trend_draws_the_spec_limit(self) -> None:
        records = [{
            "ended_at": 1_700_000_000_000 + index * 3_600_000,
            "deltas": [_delta("Temp_T0-T1", 1 + index * 0.1, 2.8)],
        } for index in range(6)]
        self.assertEqual(run_preset("trend", records)["panels"][0]["marks"][0], {"name": "上限", "y": 2.8})

    def test_heatmap_uses_the_mean_delta(self) -> None:
        records = [
            {"machine_id": "M1", "slot_index": 1, "deltas": [_delta("Temp_T0-T1", 3)]},
            {"machine_id": "M1", "slot_index": 1, "deltas": [_delta("Temp_T0-T1", 5)]},
        ]
        panels, _ = compile_stored(run_preset("heatmap", records))
        self.assertEqual(panels[0]["option"]["series"][0]["data"], [[0, 0, 4.0]])

    def test_slot_box_is_one_panel_per_over_limit_delta(self) -> None:
        records = [{
            "machine_id": "M1",
            "slot_index": slot,
            "deltas": [_delta("Temp_T0-T1", 5, 2), _delta("Temp_T1-T2", 9, 4)],
        } for slot in (1, 2)]
        result = run_preset("slot_rc", records)
        self.assertEqual([panel["title"] for panel in result["panels"]], ["Temp_T0-T1", "Temp_T1-T2"])
        panels, error = compile_stored(result)
        self.assertEqual(error, "")
        self.assertEqual(panels[0]["option"]["series"][0]["type"], "boxplot")


class FigurePdfTests(unittest.TestCase):
    def test_reads_heatmap_values_from_panel_options(self) -> None:
        rows = chart_bars({"panels": [{"option": {"series": [{"type": "heatmap", "data": [[0, 1, 40]]}]}}]})
        self.assertEqual(rows, [("1", 40.0)])
