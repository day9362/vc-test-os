from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

from app.identity import current_identity
from app.tools.data import vc_data
from app.tools.line import vc_line
from app.tools.operate import vc_operate
from app.tools.plan import vc_plan
from app.tools.quality import vc_quality

WRITE_TOOLS = {"vc_plan", "vc_operate", "vc_quality"}


class ReadonlyGate(Middleware):
    """没有用户令牌的外部客户端看不到、也调不了写工具。"""

    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        if current_identity().readonly:
            return [tool for tool in tools if tool.name not in WRITE_TOOLS]
        return tools

    async def on_call_tool(self, context, call_next):
        if context.message.name in WRITE_TOOLS and current_identity().readonly:
            raise ToolError("FORBIDDEN：只读模式不能执行写操作。外部客户端只能使用 vc_line 和 vc_data。")
        return await call_next(context)


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        "vc-testos",
        instructions=(
            "VC-TestOS 均热板测试平台。vc_line 看实时现状，vc_data 查历史数据和目录，"
            "vc_plan 写方案，vc_operate 操作设备和生产，vc_quality 处理告警、补偿和报告。"
            "中、高风险写操作会返回 APPROVAL_REQUIRED，告诉用户去页面批准，不要重复调用。"
        ),
    )
    for tool in (vc_line, vc_data, vc_plan, vc_operate, vc_quality):
        mcp.tool(tool)
    mcp.add_middleware(ReadonlyGate())
    return mcp
