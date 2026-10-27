from dataclasses import dataclass
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from app.models.dto.report import ReportDataOut

_FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
_LEFT = 36
_RIGHT = 36


@dataclass(frozen=True)
class PdfFigure:
    title: str
    prompt: str
    results: list[tuple[str, str]]
    bars: list[tuple[str, float]]
    image: bytes | None = None


def render_report_pdf(data: ReportDataOut, summary_lines: list[str] | None = None, figures: list[PdfFigure] | None = None) -> bytes:
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
    if summary_lines:
        y = _text(page, width, y, "AI 总结", 13)
        for index, line in enumerate(summary_lines, start=1):
            y = _text(page, width, y, f"{index}. {line}", 10)
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
    y = _figures(page, width, y, figures or [])
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


def chart_bars(option: dict | None) -> list[tuple[str, float]]:
    if not isinstance(option, dict):
        return []
    series = option.get("series") or []
    if isinstance(series, dict):
        series = [series]
    if not isinstance(series, list):
        return []
    axis = option.get("xAxis") or {}
    if isinstance(axis, list):
        axis = axis[0] if axis else {}
    labels = axis.get("data") if isinstance(axis, dict) else None
    if not isinstance(labels, list):
        labels = []
    rows: list[tuple[str, float]] = []
    for item in series:
        if not isinstance(item, dict):
            continue
        data = item.get("data")
        if not isinstance(data, list):
            continue
        name = str(item.get("name") or "").strip()
        for index, value in enumerate(data):
            number = _number(value)
            if number is None:
                continue
            label = str(labels[index]) if index < len(labels) else str(index + 1)
            if name and len(series) > 1:
                label = f"{label} {name}"
            rows.append((label[:16], number))
            if len(rows) >= 24:
                return rows
    return rows


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return _number(value.get("value"))
    if isinstance(value, list):
        numbers = [float(item) for item in value if isinstance(item, (int, float)) and not isinstance(item, bool)]
        if not numbers:
            return None
        return numbers[len(numbers) // 2]
    return None


def _figures(page: canvas.Canvas, width: float, y: float, figures: list[PdfFigure]) -> float:
    if not figures:
        return y
    y = _text(page, width, y, "补充分析", 13)
    for item in figures:
        y = _text(page, width, y, item.title or item.prompt or "补充分析", 12)
        if item.prompt and item.prompt != item.title:
            y = _text(page, width, y, item.prompt, 9)
        if item.image:
            y = _image(page, width, y, item.image)
        elif item.bars:
            top = max((value for _, value in item.bars), default=1)
            y = _bars(page, width, y, "", item.bars, top, "")
        for name, value in item.results:
            y = _text(page, width, y, f"{name}：{value}", 10)
        y -= 8
    return y


def _image(page: canvas.Canvas, width: float, y: float, content: bytes) -> float:
    try:
        image = ImageReader(BytesIO(content))
        source_w, source_h = image.getSize()
    except Exception:
        return y
    if source_w <= 0 or source_h <= 0:
        return y
    max_w = width - _LEFT - _RIGHT
    scale = min(max_w / source_w, 220 / source_h, 1)
    draw_w = source_w * scale
    draw_h = source_h * scale
    if y - draw_h < 48:
        page.showPage()
        y = A4[1] - 48
    page.drawImage(image, _LEFT, y - draw_h, draw_w, draw_h, mask="auto")
    return y - draw_h - 12


def _bars(page: canvas.Canvas, width: float, y: float, title: str, rows: list[tuple[str, float]], vmax: float, unit: str) -> float:
    if not rows:
        return y
    chart_h = 16 * len(rows) + (28 if title else 8)
    if y - chart_h < 48:
        page.showPage()
        y = A4[1] - 48
    if title:
        y = _text(page, width, y, title, 13)
    span = width - _LEFT - _RIGHT - 92
    top = max(vmax, 1)
    for label, value in rows:
        y -= 16
        page.setFillColorRGB(0.93, 0.94, 0.95)
        page.rect(_LEFT + 72, y - 2, span, 12, fill=1, stroke=0)
        page.setFillColorRGB(0.12, 0.35, 0.62)
        page.rect(_LEFT + 72, y - 2, span * max(min(value, top), 0) / top, 12, fill=1, stroke=0)
        page.setFillColorRGB(0.1, 0.12, 0.16)
        page.setFont(_FONT, 9)
        page.drawString(_LEFT, y, str(label)[:10])
        page.drawRightString(width - _RIGHT, y, f"{value:g}{unit}")
    return y - 16


def _text(page: canvas.Canvas, width: float, y: float, text: str, size: int) -> float:
    max_width = width - _LEFT - _RIGHT
    for line in _wrap(text, size, max_width):
        if y < 48:
            page.showPage()
            y = A4[1] - 48
        page.setFillColorRGB(0.1, 0.12, 0.16)
        page.setFont(_FONT, size)
        page.drawString(_LEFT, y, line)
        y -= size + 8
    return y


def _wrap(text: str, size: int, max_width: float) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            lines.append(current)
            current = ""
            continue
        trial = current + char
        if current and pdfmetrics.stringWidth(trial, _FONT, size) > max_width:
            lines.append(current)
            current = char
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [""]
