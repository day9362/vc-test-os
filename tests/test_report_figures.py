import unittest

from app.core.errors import AppError
from app.service.reports.sandbox import reject_code, sanitize_option


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
