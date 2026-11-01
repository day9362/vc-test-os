import unittest

from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.identity import Identity, force_identity
from app.server import build_mcp


class ReadonlyGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        force_identity(None)

    async def test_readonly_sees_read_tools_only(self):
        async with Client(build_mcp()) as client:
            names = sorted(tool.name for tool in await client.list_tools())
        self.assertEqual(names, ["vc_data", "vc_line"])

    async def test_readonly_cannot_call_write_tool(self):
        async with Client(build_mcp()) as client:
            with self.assertRaises(ToolError):
                await client.call_tool("vc_quality", {"action": "ack", "alarm_ids": ["A1"]})

    async def test_user_sees_all_tools(self):
        force_identity(Identity("user-token"))
        async with Client(build_mcp()) as client:
            names = sorted(tool.name for tool in await client.list_tools())
        self.assertEqual(names, ["vc_data", "vc_line", "vc_operate", "vc_plan", "vc_quality"])


if __name__ == "__main__":
    unittest.main()
