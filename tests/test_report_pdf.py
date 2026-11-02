import unittest

from app.models.dto.report import ReportDataOut
from app.models.orm.run import RunOrm
from app.models.dto.report import ExportBlock
from app.service.reports.pdf import PdfFigure, chart_bars, render_page_pdf, render_report_pdf
from app.service.reports.report_service import _delta_profile_from


def _data() -> ReportDataOut:
    return ReportDataOut.model_validate({
        "batches": [{
            "batch_id": "B-1", "model": "", "count": 4, "tested": 4, "passed": 4, "failed": 0, "aborted": 0,
            "plan_id": "P", "plan_version": 1, "machine_ids": ["M01"], "started_at": 1, "ended_at": 2,
            "state": "done", "rc_mean": 2.9, "rc_sd": 0.1, "top_fail": "", "top_fail_count": 0,
        }],
        "summary": {
            "tested": 4, "passed": 4, "failed": 0, "aborted": 0, "yield_rate": 100,
            "rc_mean": 2.9, "rc_sd": 0.1, "cpk_t01": -1, "usl_t01": 2.8, "machine_count": 1,
        },
        "machine_yield": [{"machine_id": "M01", "n": 4, "passed": 4}],
        "rc_histogram": {"edges": [2.0, 3.0], "counts": {"B-1": [4]}},
        "fail_pareto": [],
        "delta_profile": {"items": [], "mean": {}, "p95": None, "limit": []},
        "compare": [{"batch_id": "B-1", "yield_rate": 100, "rc_mean": 2.9}],
    })


class ReportPdfTests(unittest.TestCase):
    def test_reads_bar_values_from_an_echarts_option(self) -> None:
        rows = chart_bars({
            "xAxis": {"type": "category", "data": ["1", "2"]},
            "series": [{"type": "bar", "data": [2.8, {"value": 3.1}]}],
        })
        self.assertEqual(rows, [("1", 2.8), ("2", 3.1)])

    def test_reads_the_middle_of_a_boxplot(self) -> None:
        rows = chart_bars({"series": [{"type": "boxplot", "data": [[1, 2, 3, 4, 5]]}]})
        self.assertEqual(rows, [("1", 3.0)])

    def test_pdf_contains_the_summary_and_the_figure_result(self) -> None:
        plain = render_report_pdf(_data())
        rich = render_report_pdf(
            _data(),
            ["本批次测了 4 片，良率 100%。"],
            [PdfFigure(title="槽位 Rc", prompt="按槽位号画 Rc", results=[("槽位 1", "2.8059")], bars=[("1", 2.8059)])],
        )
        self.assertTrue(plain.startswith(b"%PDF"))
        self.assertTrue(rich.startswith(b"%PDF"))
        self.assertGreater(len(rich), len(plain))

    def test_page_pdf_keeps_the_visible_heading_and_drops_other_charts(self) -> None:
        raw = render_page_pdf([
            ExportBlock(kind="h1", text="AI 总结 · 机台"),
            ExportBlock(kind="text", text="M01 槽1 的 Temp_T0-T1 极差 0.786 ℃。"),
            ExportBlock(kind="table", title="卡限项", columns=["项", "均值"], rows=[["Temp_T0-T1", "5.973 ℃"]]),
        ])
        self.assertTrue(raw.startswith(b"%PDF"))
        self.assertGreater(len(raw), 800)


def _run(deltas: dict, plan: str = "P", version: int = 1) -> RunOrm:
    return RunOrm(
        run_id=f"{plan}-{version}-{deltas}", machine_id="M1", slot_index=1,
        plan_id=plan, plan_version=version, status="COMPLETED", ended_at=1,
        result={"deltas": deltas},
    )


class DeltaProfileTests(unittest.TestCase):
    def test_axis_is_only_the_limited_delta_items(self) -> None:
        limits = {
            ("P", 1): {
                "delta_t0_t1": ("Temp_T0-T1", 0, 2.8),
                "delta_t1_t2": ("Temp_T1-T2", 0, 4.0),
                "thermal_resistance": ("Rc", None, 5),
            },
            ("P", 2): {"delta_t1_t8": ("Temp_T1-T8", 0, 9)},
        }
        rows = [
            _run({"Temp_T0-T1": 2.0, "Temp_T1-T2": 3.0, "Temp_Ta": 25, "Rc": 1.2}),
            _run({"Temp_T0-T1": 99999, "Temp_T1-T2": 3.4, "Temp_Ta": 24}),
        ]
        profile = _delta_profile_from({"B": rows, "C": [_run({"Temp_Ta": 25})]}, limits, False)
        self.assertEqual(profile.items, ["Temp_T0-T1", "Temp_T1-T2"])
        self.assertEqual(profile.limit, [2.8, 4.0])
        self.assertEqual(profile.mean["B"], [2.0, 3.2])
        self.assertEqual(profile.mean["C"], [None, None])
        self.assertIsNone(profile.p95)

    def test_single_batch_p95_uses_the_upper_reading(self) -> None:
        limits = {("P", 1): {"delta_t0_t1": ("Temp_T0-T1", 0, 2.8)}}
        rows = [_run({"Temp_T0-T1": value}) for value in (1.0, 2.0, 3.0)]
        profile = _delta_profile_from({"B": rows}, limits, True)
        self.assertEqual(profile.p95, [3.0])

    def test_disagreement_on_the_high_limit_is_left_blank(self) -> None:
        limits = {
            ("P", 1): {"delta_t0_t1": ("Temp_T0-T1", 0, 2.8)},
            ("Q", 1): {"delta_t0_t1": ("Temp_T0-T1", 0, 3.4)},
        }
        rows = [_run({"Temp_T0-T1": 2.0}, "P"), _run({"Temp_T0-T1": 2.1}, "Q")]
        profile = _delta_profile_from({"B": rows}, limits, True)
        self.assertEqual(profile.limit, [None])
