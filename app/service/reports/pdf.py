from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from app.models.dto.report import ReportDataOut

_FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(_FONT))


def render_report_pdf(data: ReportDataOut, figure_note: str | None = None) -> bytes:
    buffer = BytesIO()
    page = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 48
    y = _line(page, width, y, "VC-TestOS 批次报告", 16)
    y = _line(page, width, y, "数据截止到当前", 10)
    y -= 8
    summary = data.summary
    y = _line(page, width, y, f"测试 {summary.tested}  通过 {summary.passed}  失败 {summary.failed}  中止 {summary.aborted}", 11)
    y = _line(page, width, y, f"良率 {summary.yield_rate}%  Rc 均值 {summary.rc_mean}  Rc SD {summary.rc_sd}", 11)
    y = _line(page, width, y, f"Cpk T01 {summary.cpk_t01}  USL {summary.usl_t01}  机台数 {summary.machine_count}", 11)
    if figure_note:
        y -= 6
        y = _line(page, width, y, figure_note, 10)
    y -= 10
    y = _line(page, width, y, "批次", 13)
    for batch in data.batches:
        text = (
            f"{batch.batch_id}  {batch.model}  tested={batch.tested}  pass={batch.passed}  "
            f"fail={batch.failed}  abort={batch.aborted}  Rc={batch.rc_mean}  状态={batch.state}"
        )
        y = _line(page, width, y, text, 10)
    y -= 8
    y = _line(page, width, y, "机台良率", 13)
    for item in data.machine_yield:
        y = _line(page, width, y, f"{item.machine_id}  n={item.n}  passed={item.passed}", 10)
    y -= 8
    y = _line(page, width, y, "失效 Pareto", 13)
    if not data.fail_pareto:
        y = _line(page, width, y, "无", 10)
    for item in data.fail_pareto:
        y = _line(page, width, y, f"{item.item}  {item.count}", 10)
    y -= 8
    y = _line(page, width, y, "批次对比", 13)
    if not data.compare:
        y = _line(page, width, y, "无（tested=0 的批次不参与计算）", 10)
    for item in data.compare:
        y = _line(page, width, y, f"{item.batch_id}  良率 {item.yield_rate}%  Rc {item.rc_mean}", 10)
    page.save()
    return buffer.getvalue()


def _line(page: canvas.Canvas, width: float, y: float, text: str, size: int) -> float:
    if y < 48:
        page.showPage()
        y = A4[1] - 48
    page.setFont(_FONT, size)
    page.drawString(36, y, text[:110])
    return y - (size + 6)
