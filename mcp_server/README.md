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

| 请求头 | 可见工具 | 能做的事 |
| --- | --- | --- |
| `Authorization: Bearer <用户 JWT>` | 全部 6 个 | 查询和写动作 |
| 无令牌 | 全部 6 个 | 只能查询 |

## 工具

按实体划分，动作写在 `action` 里：

- `vc_machine`：机台。含启停、上方案（`dispatch`）、仿真、补偿
- `vc_plan`：方案的查询、起草、发布
- `vc_board`：板子和批次。拉新是 `create_batch`
- `vc_run`：测试记录，只查
- `vc_alarm`：告警
- `vc_report`：报告

中、高风险写动作返回 `APPROVAL_REQUIRED`，由页面批准后带 `confirm_id` + HMAC `approval` 再调一次。明细见 `DESIGN.md`。

## 测试

```powershell
$env:PYTHONPATH = "d:\AI项目\backend_api\mcp_server"
d:\AI项目\backend_api\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```
