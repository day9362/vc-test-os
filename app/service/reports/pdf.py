from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from app.models.dto.report import ReportDataOut

_FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
_LEFT = 36
_RIGHT = 36


def render_report_pdf(data: ReportDataOut, figure_note: str | None = None) -> bytes:
    buffer = BytesIO()
    page = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 48
    summary = data.summary
    y = _text(page, width, y, "VC-TestOS 批次报告", 16)
    names = "、".join(item.batch_id for item in data.batches) or "—"
    y = _text(page, width, y, names, 10)
    y = _text(
        page,
        width,
        y,
        f"测试 {summary.tested} 片 · 通过 {summary.passed} · 不合格 {summary.failed} · 中止 {summary.aborted}",
        11,
    )
    y = _text(
        page,
        width,
        y,
        f"良率 {summary.yield_rate}% · Rc 均值 {summary.rc_mean} · SD {summary.rc_sd} · Cpk {summary.cpk_t01}",
        11,
    )
    if figure_note:
        y = _text(page, width, y, figure_note, 9)
    yields = [
        (item.machine_id, round(100 * item.passed / item.n, 1) if item.n else 0)
        for item in data.machine_yield
    ]
    y = _bars(page, width, y, "机台良率", yields, 100, "%")
    hist = _histogram_bars(data)
    y = _bars(page, width, y, "Rc 分布", hist, max((value for _, value in hist), default=1), "")
    pareto = [(item.item, item.count) for item in data.fail_pareto[:8]]
    y = _bars(page, width, y, "不合格项", pareto, max((value for _, value in pareto), default=1), "")
    if len(data.compare) > 1:
        y = _bars(page, width, y, "批次良率对比", [(item.batch_id, item.yield_rate) for item in data.compare], 100, "%")
    page.save()
    return buffer.getvalue()


def _histogram_bars(data: ReportDataOut) -> list[tuple[str, float]]:
    edges = data.rc_histogram.edges
    counts = data.rc_histogram.counts
    if len(edges) < 2 or not counts:
        return []
    width = max(1, (len(edges) - 1) // 8)
    labels: list[tuple[str, float]] = []
    total = [0] * (len(edges) - 1)
    for series in counts.values():
        for index, value in enumerate(series[: len(total)]):
            total[index] += value
    index = 0
    while index < len(total):
        chunk = total[index:index + width]
        label = f"{edges[index]:.2f}"
        labels.append((label, float(sum(chunk))))
        index += width
    return labels


def _bars(page: canvas.Canvas, width: float, y: float, title: str, rows: list[tuple[str, float]], vmax: float, unit: str) -> float:
    if not rows:
        return y
    chart_h = 16 * len(rows) + 28
    if y - chart_h < 48:
        page.showPage()
        y = A4[1] - 48
    y = _text(page, width, y, title, 13)
    span = width - _LEFT - _RIGHT - 92
    top = max(vmax, 1)
    for label, value in rows:
        y -= 16
        page.setFillColorRGB(0.93, 0.94, 0.95)
        page.rect(_LEFT + 72, y - 2, span, 12, fill=1, stroke=0)
        page.setFillColorRGB(0.12, 0.35, 0.62)
        page.rect(_LEFT + 72, y - 2, span * min(value, top) / top, 12, fill=1, stroke=0)
        page.setFillColorRGB(0.1, 0.12, 0.16)
        page.setFont(_FONT, 9)
        page.drawString(_LEFT, y, str(label)[:10])
        page.drawRightString(width - _RIGHT, y, f"{value:g}{unit}")
    return y - 16


def _text(page: canvas.Canvas, width: float, y: float, text: str, size: int) -> float:
    if y < 48:
        page.showPage()
        y = A4[1] - 48
    page.setFillColorRGB(0.1, 0.12, 0.16)
    page.setFont(_FONT, size)
    page.drawString(_LEFT, y, text[:90])
    return y - (size + 8)
