# VC-TestOS MCP Server

对接 VC-TestOS 后端 `/api/v1` 的 MCP 服务，占用 `8100`，供 AI Agent 与外部只读客户端使用。

## 启动

本地进程：

```powershell
cd d:\AI项目\backend_api\mcp_server
copy .env.example .env
# 填写 VC_USERNAME / VC_PASSWORD（只读服务账号）和 MCP_APPROVAL_SECRET（与后端相同）
$env:PYTHONPATH = "d:\AI项目\backend_api\mcp_server"
d:\AI项目\backend_api\.venv\Scripts\python.exe -m app.main
```

Docker（与前后端一起）：见仓库 `docker/README.md`，根目录执行 `docker compose up -d --build`。

健康检查：`GET http://127.0.0.1:8100/health`

MCP 地址：`http://127.0.0.1:8100/mcp/`

## 身份

| 请求头 | 可见工具 |
| --- | --- |
| `Authorization: Bearer <用户 JWT>` | 全部 5 个 |
| 无令牌 | 只有 `vc_line`、`vc_data` |

## 工具

- `vc_line` / `vc_data`：只读
- `vc_plan` / `vc_operate` / `vc_quality`：写；中、高风险返回 `APPROVAL_REQUIRED`，由页面批准后带 `confirm_id` + HMAC `approval` 再调一次

## 测试

```powershell
$env:PYTHONPATH = "d:\AI项目\backend_api\mcp_server"
d:\AI项目\backend_api\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```
