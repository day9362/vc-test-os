import unittest

from app.models.dto.report import ReportDataOut
from app.service.reports.pdf import PdfFigure, chart_bars, render_report_pdf


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
