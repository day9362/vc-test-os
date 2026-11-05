from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

from app.identity import current_identity
from app.tools.alarm import vc_alarm
from app.tools.board import vc_board
from app.tools.machine import vc_machine
from app.tools.plan import vc_plan
from app.tools.report import vc_report
from app.tools.run import vc_run

# 同一个工具里既有查询也有修改。只读客户端看得到全部工具，但只能调用查询动作。
WRITE_ACTIONS = {
    "from_text",
    "validate",
    "save_draft",
    "delete_draft",
    "publish",
    "power_on",
    "power_off",
    "reset",
    "maintenance",
    "slot_load",
    "slot_start",
    "slot_test",
    "slot_abort",
    "slot_clear_error",
    "dispatch",
    "production_precheck",
    "production_start",
    "production_stop",
    "sim_speed",
    "sim_scenario",
    "sim_fault",
    "suggest_compensation",
    "apply_compensation",
    "create_batch",
    "requeue",
    "ack",
    "unack",
    "ack_all",
    "rerun_attribution",
    "report_summary",
    "report_figure",
    "report_export",
}


def _action(message) -> str | None:
    raw = getattr(message, "arguments", None)
    if isinstance(raw, dict):
        value = raw.get("action")
        return value if isinstance(value, str) else None
    return None


class ReadonlyGate(Middleware):
    """没有用户令牌的外部客户端可以查询，不能执行会改数据的 action。"""

    async def on_call_tool(self, context, call_next):
        if current_identity().readonly and _action(context.message) in WRITE_ACTIONS:
            raise ToolError("FORBIDDEN：只读模式不能执行写操作。外部客户端只能查询。")
        return await call_next(context)


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        "vc-testos",
        instructions=(
            "VC-TestOS 均热板测试平台。工具按实体划分，动作写在 action 里，不要为单个动作另找工具。"
            "vc_machine 管机台（含启停、上方案、仿真、补偿），vc_plan 管方案，vc_board 管板子和批次（含拉新），"
            "vc_run 查测试记录，vc_alarm 管告警，vc_report 管报告。"
            "中、高风险写操作会返回 APPROVAL_REQUIRED，告诉用户去页面批准，不要重复调用。"
        ),
    )
    for tool in (vc_machine, vc_plan, vc_board, vc_run, vc_alarm, vc_report):
        mcp.tool(tool)
    mcp.add_middleware(ReadonlyGate())
    return mcp
