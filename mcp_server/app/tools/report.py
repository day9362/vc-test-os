from typing import Literal

from app.tools.quality import run_quality

ReportAction = Literal["report_summary", "report_figure", "report_export"]


async def vc_report(
    action: ReportAction,
    batch_ids: list[str] | None = None,
    prompt: str | None = None,
    figure_id: str | None = None,
    figure_ids: list[str] | None = None,
    summary_lines: list[str] | None = None,
    confirm_id: str | None = None,
    approval: str | None = None,
) -> dict:
    """VC-TestOS 测试报告。总结、出图、导出 PDF 都是这个工具的 action。

    action:
    - report_summary：生成批次报告结论，要 batch_ids。直接执行。
    - report_figure：给 batch_ids 和 prompt 生成图表（异步，返回 figure_id）；只给 figure_id 时查进度。直接执行。
    - report_export：导出 PDF 报告，要 batch_ids，可带 figure_ids、summary_lines。需批准。
    confirm_id、approval 只由页面批准后使用，不要自己填写。
    """
    return await run_quality(
        action,
        batch_ids=batch_ids,
        prompt=prompt,
        figure_id=figure_id,
        figure_ids=figure_ids,
        summary_lines=summary_lines,
        confirm_id=confirm_id,
        approval=approval,
        tool="vc_report",
    )
