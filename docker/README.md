# Docker 一键部署

把 PostgreSQL、Redis、后端、MCP、前端一起拉起来。报告图沙箱镜像会顺带构建。

## 准备

1. 安装并启动 Docker Desktop（Linux 容器模式）。
2. 在仓库根目录准备 `.env`（可从 `.env.example` 复制），至少填：

```env
JWT_SECRET=请改成随机串
CLUSTER_TOKEN=
MCP_APPROVAL_SECRET=前后端共用的随机串
ANTHROPIC_BASE_URL=
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=deepseek-flash
VC_USERNAME=只读服务账号
VC_PASSWORD=
```

容器内会覆盖这些地址，不必改成服务名：

- `DATABASE_URL` → `postgres`
- `REDIS_URL` → `redis`
- `MCP_URL` → `mcp:8100`
- `VC_API_BASE` → `backend:8000`

## 启动

```powershell
cd d:\AI项目\backend_api
docker compose up -d --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://127.0.0.1:8080 |
| 后端 API | http://127.0.0.1:8000 |
| MCP | http://127.0.0.1:8100/mcp/ |
| MCP 健康检查 | http://127.0.0.1:8100/health |
| Postgres | 127.0.0.1:5433 |
| Redis | 127.0.0.1:6380 |

查看状态与日志：

```powershell
docker compose ps
docker compose logs -f backend mcp frontend
```

停止：

```powershell
docker compose down
```

数据卷（`vcos_pg18` / 报告 / Agent 会话）会保留；连卷一起清掉用 `docker compose down -v`。

## 说明

- 前端 Nginx 把 `/api`、`/files`、WebSocket 转到 `backend`。
- 后端通过 `docker.sock` 调用宿主机 Docker 跑报告图沙箱；沙箱工作目录在命名卷 `vcos_sandbox`。
- `claude-agent-sdk` 体积较大，首次构建后端镜像会较慢。
- 以后改 MCP / 后端 / 前端代码，重新 `docker compose up -d --build` 即可，不必等功能全部做完再部署。
- 启动前请先停掉本机占用 `8000` / `8100` 的旧后端或 MCP 进程，否则会出现「容器健康但浏览器打到旧服务」的情况。
- 容器 Postgres 为 18 版，宿主机端口是 `5433`（`5432` 留给本机 PostgreSQL 服务）。
- 容器 Redis 宿主机端口是 `6380`（`6379` 常被本机 redis-server 占用）。
- 后端默认用 `frontui` schema；要换用 `DOCKER_DATABASE_SEARCH_PATH` 覆盖。
- 后端镜像通过 `docker/backend/openssl.cnf` 限定 TLS 曲线：集群网关不接受 OpenSSL 3.5 默认的抗量子大握手包，不加会导致同步全部超时、页面不刷新。
- 报告图沙箱需要后端镜像里的 `docker-cli` + 挂载的 `docker.sock`；确认有 `vc-test-os-sandbox:1` 镜像。

## 从本机 PostgreSQL 迁移数据

把本机 `vcos` 库（所有 schema）整库导入容器：

```powershell
$env:PGPASSWORD = "vcos"
D:\postgresql\bin\pg_dump.exe -h 127.0.0.1 -p 5432 -U vcos -d vcos -Fc --no-owner --no-privileges -f $env:TEMP\vcos_full.dump
docker cp $env:TEMP\vcos_full.dump backend_api-postgres-1:/tmp/vcos_full.dump
docker compose exec -T postgres pg_restore -U vcos -d vcos --no-owner --no-privileges --clean --if-exists /tmp/vcos_full.dump
docker compose exec -T postgres rm -f /tmp/vcos_full.dump
docker compose restart backend mcp
```
