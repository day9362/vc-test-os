from typing import Literal

from app.tools.line import vc_line
from app.tools.quality import run_quality

AlarmAction = Literal["alarms", "attribution", "ack", "unack", "ack_all", "rerun_attribution"]


async def vc_alarm(
    action: AlarmAction,
    alarm_id: str | None = None,
    alarm_ids: list[str] | None = None,
    machine_id: str | None = None,
    acked: bool | None = None,
    level: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    confirm_id: str | None = None,
    approval: str | None = None,
) -> dict:
    """VC-TestOS 告警。查询、确认、重新归因都是这个工具的 action。

    action:
    - alarms：告警列表，可按 acked、machine_id、level（critical/major/minor）筛选，分页用 cursor、limit。
    - attribution：某条告警的归因结论，要 alarm_id。
    - ack / unack：确认或取消确认告警，要 alarm_ids。直接执行。
    - ack_all：确认全部未确认告警。需批准。
    - rerun_attribution：重新归因一条告警，要 alarm_id。直接执行。
    confirm_id、approval 只由页面批准后使用，不要自己填写。
    """
    if action in {"alarms", "attribution"}:
        return await vc_line(
            action,
            machine_id=machine_id,
            acked=acked,
            level=level,
            alarm_id=alarm_id,
            cursor=cursor,
            limit=limit,
        )
    return await run_quality(
        action,
        alarm_ids=alarm_ids,
        alarm_id=alarm_id,
        confirm_id=confirm_id,
        approval=approval,
        tool="vc_alarm",
    )
