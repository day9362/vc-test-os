# VC-TestOS MCP Server 设计文档

> 状态：按实体划分。公开工具 6 个，动作都写在 `action` 里。

## 1. 目标

为 VC-TestOS 单独开发一套 MCP 工具，让 AI Agent 和外部 MCP 客户端通过**系统平台**查看产线、分析数据、编写方案、操作设备。

- **只对接 VC-TestOS 后端 `/api/v1`**。MCP 不直接访问仿真集群或真实设备，数据源的差异全部由后端屏蔽。
- **少工具、多参数**。系统里一个实体对应一个工具。查询和修改放在同一个工具里，用 `action` 区分，不按读和写拆成两套工具。
- **动作不单独成工具**。启停、拉新、上方案、装板、开测都是某个实体工具的 `action`。
- **写操作分级**。低风险直接执行；中、高风险必须由用户在页面批准，模型自己无法绕过。

六个公开工具：

| 工具 | 实体 | 查询 | 会改数据的 action |
| --- | --- | --- | --- |
| `vc_machine` | 机台、槽位、仿真、补偿、连续生产 | 概况、机台、槽位、当前生产、补偿、审计、仿真目录 | 上下电、复位、维修、单槽、上方案、启停、仿真、写入补偿 |
| `vc_plan` | 测试方案 | 方案列表和详情 | 起草、校验、保存、删除草稿、发布 |
| `vc_board` | 板子和批次 | 单板、批次、型号、缺陷种类 | 拉新（`create_batch`）、标准样品放回待测（`requeue`） |
| `vc_run` | 测试记录 | 记录、对比、趋势、导出 CSV | 无 |
| `vc_alarm` | 告警 | 列表、归因 | 确认、取消确认、全部确认、重新归因 |
| `vc_report` | 测试报告 | 按 `figure_id` 查图表进度 | 总结、出图、导出 PDF |

上方案是 `vc_machine` 的 `dispatch`，不是 `vc_plan` 的动作。发布方案不会自动装到机台。

## 2. 已确定的决策

| 问题 | 决定 |
| --- | --- |
| 端口 | 直接占用 `8100`，替换现有服务；后端 `mcp_url` 不用改 |
| 工具划分 | 按实体，不按读写。公开工具就是上面 6 个 |
| 外部客户端权限 | 看得到全部工具，但只能调用查询类 `action` |
| 低风险写操作 | 不需要页面批准，直接执行 |
| 单槽控制、生成批次 | 已做。生成批次在 `vc_board`，单槽在 `vc_machine` |

## 3. 架构

```
浏览器 ──REST/WS──▶ VC-TestOS 后端 /api/v1 ──▶ 仿真集群 / 真实设备
                         ▲          │
                         │          │ 批准后带 approval 回调
AI Agent ──MCP(用户令牌)──┤          ▼
                     mcp_server :8100
外部客户端 ──MCP(服务账号，只读)──┘
```

| 项 | 取值 |
| --- | --- |
| 传输 | Streamable HTTP，`http://127.0.0.1:8100/mcp/` |
| 服务名 | `vc-testos`（Agent 中工具全名：`mcp__vc-testos__vc_machine`） |
| 健康检查 | `GET /health`：探测后端 `/api/v1/sync/jobs/status`，返回 MCP 自身状态与后端状态 |
| 依赖 | `fastmcp`、`httpx`、`pydantic-settings`、`redis` |

`vc_line`、`vc_data`、`run_operate`、`run_plan`、`run_quality` 只是内部实现，不注册成 MCP 工具。Agent 和外部客户端都看不到它们。

## 4. 身份与权限

MCP 每次请求根据 HTTP 头决定身份：

| 模式 | 识别方式 | 可见工具 | 能做的事 | 后端令牌 |
| --- | --- | --- | --- | --- |
| 用户模式 | 请求头带 `Authorization: Bearer <用户 JWT>`（Agent 调用时由后端放入） | 全部 6 个 | 查询和写动作 | 原样转发，审计落在真实用户名下 |
| 只读模式 | 没有用户令牌 | 全部 6 个 | 只能查询 | MCP 用 `.env` 中的服务账号登录后端获取，401 时重新登录一次 |

- 只读模式下 `tools/list` 仍返回 6 个工具，因为查询和修改在同一个工具里。调用写 `action` 时中间件直接返回 `FORBIDDEN`，函数内部也会再拦一次。
- 写 `action` 包括：方案的 `from_text`、`validate`、`save_draft`、`delete_draft`、`publish`；机台的上下电、复位、维修、单槽、`dispatch`、生产预检和启停、仿真、补偿建议和写入；板子的 `create_batch`、`requeue`；告警的确认和重新归因；报告的总结、出图、导出。
- 用户令牌失效时返回 `UNAUTHORIZED`，不回退到服务账号，避免越权。

## 5. 统一约定

### 5.1 入参

- 第一个参数固定为 `action`（枚举）。其余参数按动作选填，工具描述里写清每个动作需要哪些参数。
- 分页：`cursor` + `limit`（默认 20，上限 200）。
- 时间：`window` 取 `1h` / `2h` / `8h` / `24h` / `7d`，或用 `from_ms` / `to_ms` 指定毫秒时间戳。
- 多台机台：统一用 `machine_ids: list[str]`，单台也写成一个元素的列表。`reset` 可以不给 `machine_ids`，表示全部在线机台。`sim_speed` 必须给出 `machine_ids`，不会改全部机台。
- `detail: bool = false`：默认返回精简字段，需要时再取完整对象，控制 token 消耗。

### 5.2 返回

成功：

```json
{
  "ok": true,
  "summary": "M01、M02 已上电，M03 正在维修未处理。",
  "data": {},
  "next_cursor": null,
  "hints": ["M03 需要先退出维修模式"]
}
```

失败：

```json
{
  "ok": false,
  "summary": "M02 正在维修，不能上电。",
  "error": { "code": "CONFLICT", "status": 409, "message": "M02 正在维修" },
  "hints": ["先退出维修模式再上电"]
}
```

等待批准（中、高风险写操作第一次调用的返回，见第 6 节）：

```json
{
  "ok": false,
  "summary": "需要用户批准：给 M01、M02 关机，正在测试的槽会被中止。",
  "error": { "code": "APPROVAL_REQUIRED" },
  "approval": {
    "confirm_id": "cf_8f3a…",
    "tool": "vc_machine",
    "action": "power_off",
    "risk": "high",
    "sentence": "给 M01、M02 关机",
    "effects": ["M01 3 号槽正在测试，将被标记为中止"],
    "precheck": null,
    "expires_at": 1793460000000
  }
}
```

- `summary` 是给模型直接转述的一句中文结论；`hints` 是可选的下一步建议。
- `error.code` 沿用后端错误码（`NOT_FOUND`、`VALIDATION_ERROR`、`CONFLICT`、`MACHINE_DISCONNECTED`、`CLUSTER_TIMEOUT` 等），另加 MCP 自己的：

| code | 含义 |
| --- | --- |
| `BACKEND_UNAVAILABLE` | 系统平台超时或不可达（不是设备故障） |
| `FORBIDDEN` | 只读模式调用了写动作 |
| `APPROVAL_REQUIRED` | 需要用户批准 |
| `APPROVAL_INVALID` | 批准凭证不对、已过期或已用过 |
| `BAD_ARGUMENT` | 缺参数或参数组合不合法，`hints` 里写明缺什么 |
| `PARTIAL` | 多台操作里有的成功、有的失败。`detail.done` 和 `detail.failed` 分开列。已经成功的不要再发 |

## 6. 写操作分级与批准

未出现在下表里的动作是 low：查询全部是 low；`from_text`、`validate`、`save_draft`、`ack`、`unack`、`rerun_attribution`、`suggest_compensation`、`report_summary`、`report_figure`、`production_precheck` 也是 low，直接执行。

### 6.1 风险等级

| 等级 | 处理 | 动作 |
| --- | --- | --- |
| medium | 页面批准 | `vc_plan`：`publish`、`delete_draft`。`vc_machine`：`dispatch`、`power_on`、`maintenance`、`slot_load`、`slot_start`、`slot_test`、`slot_clear_error`、`production_start`、`sim_speed`、`apply_compensation`。`vc_board`：`create_batch`、`requeue`。`vc_alarm`：`ack_all`。`vc_report`：`report_export` |
| high | 页面批准（红色提示） | `vc_machine`：`power_off`、`reset`、`slot_abort`、`production_stop`、`sim_scenario`、`sim_fault` |

风险按 `(工具名, action)` 查 `approval.py` 的 `RISK`。同一个 `action` 名字不会跨工具复用。

### 6.2 批准流程

1. 模型调用中、高风险动作。MCP **不执行**，先做能做的检查（参数校验、机台状态、`production_start` 自动预检、`publish` 自动校验），然后：
   - 生成 `confirm_id`，把「用户 + 工具 + 动作 + 参数」存进 Redis（`mcp:confirm:{id}`，10 分钟过期）；
   - 返回 `APPROVAL_REQUIRED` 和 `approval` 对象。预检有 `danger` 级问题时直接返回失败，不生成 `confirm_id`。
2. 后端 Agent 运行时识别到 `APPROVAL_REQUIRED`，登记为待确认操作，页面右侧显示 `sentence`、`effects`、`risk`。
3. 用户点「批准」后，后端用共享密钥计算 `approval = HMAC-SHA256(MCP_APPROVAL_SECRET, confirm_id)`，以同一个工具调用：`{"action": <原动作>, "confirm_id": "...", "approval": "..."}`。不再传业务参数。
4. MCP 校验 `approval`、校验调用者与登记时是同一用户，取出**登记时的参数**执行，然后删除这条登记（只能用一次）。执行时把 `confirm_id` 作为后端的 `Idempotency-Key`。
5. 用户点「拒绝」或 10 分钟未处理：登记作废。

要点：

- 模型拿得到 `confirm_id`，但拿不到密钥，算不出 `approval`，所以无法自己批准。后端在调用前还会剥掉模型自己填的 `confirm_id` 和 `approval`。
- 执行时只用登记时的参数，批准后无法偷换目标机台或数值。
- 密钥 `MCP_APPROVAL_SECRET` 只放在后端和 MCP 的 `.env`，不进仓库。
- 能被页面批准后回调的工具是 `vc_machine`、`vc_plan`、`vc_board`、`vc_alarm`、`vc_report`。`vc_run` 只查不改，不进这个名单。

## 7. 工具明细

下表「后端接口」省略前缀 `/api/v1`。

### 7.1 `vc_machine` — 机台

查询和操作机台、槽位、连续生产、仿真、通道补偿。启停是 `production_start` / `production_stop`，上方案是 `dispatch`。

| action | 功能 | 主要参数 | 后端接口 | 风险 |
| --- | --- | --- | --- | --- |
| `overview` | 聚合：KPI、流程条、连续生产状态、未确认告警数、同步状态 | `window` | `GET /stats/kpi`、`/stats/pipeline`、`/production`、`/sync/jobs/status` | low |
| `machines` | 机台列表；可按状态、通信状态筛选 | `status?`、`comm?` | `GET /machines` | low |
| `machine` | 单台详情和全部槽位。`loaded=true` 再读集群上现在装的方案，没装也算成功 | `machine_id`、`detail?`、`loaded?` | `GET /machines/{id}` | low |
| `slot` | 单个槽：阶段、进度、温度、真空、当前记录；`detail=true` 附带过程曲线 | `machine_id`、`slot_index` | `GET /machines/{id}` + `GET /machines/{id}/slots/{index}/curve` | low |
| `production` | 当前连续生产：批次、方案版本、剩余数量 | — | `GET /production` | low |
| `search` | 按关键字找机台、批次、方案、测试记录 | `q`、`limit` | `GET /search` | low |
| `sim_catalog` | 仿真场景与故障种类 | — | `GET /sim/scenarios`、`GET /sim/fault-catalog` | low |
| `calibration` | 聚合：通道偏差、漂移、当前补偿、补偿建议 | `machine_id` | `GET /machines/{id}/channel-bias`、`/drifts`、`/compensation`、`/compensation/suggestion` | low |
| `calibration_history` | 补偿修改历史 | `machine_id`、`cursor`、`limit` | `GET /machines/{id}/compensation/history` | low |
| `plan_history` | 这台机用过的方案版本和测试数 | `machine_id` | `GET /machines/{id}/plan-history` | low |
| `audit` | 操作审计 | `machine_id?`、`cursor`、`limit` | `GET /audit` | low |
| `power_on` | 上电 | `machine_ids` | `POST /machines/{id}/power-on` | medium |
| `power_off` | 关机；正在测试的槽会被中止 | `machine_ids` | `POST /machines/{id}/power-off` | high |
| `reset` | 清故障复位；`machine_ids` 为空表示全部在线机台 | `machine_ids?` | `POST /machines/{id}/reset` | high |
| `maintenance` | 进入 / 退出维修模式 | `machine_ids`、`on` | `POST /machines/{id}/maintenance` | medium |
| `slot_load` | 把一片板装到槽上，不开测 | `machine_id`、`slot_index`、`serial_number` | `POST /machines/{id}/slots/{index}/load` | medium |
| `slot_start` | 对已装板的槽开测，返回 `run_id` | `machine_id`、`slot_index` | `POST /machines/{id}/slots/{index}/start` | medium |
| `slot_test` | 装板并立即开测，返回 `run_id` | `machine_id`、`slot_index`、`serial_number` | 依次调用 load 和 start | medium |
| `slot_abort` | 中止槽位测试并松开板 | `machine_id`、`slot_index` | `POST /machines/{id}/slots/{index}/abort` | high |
| `slot_clear_error` | 清除槽位错误 | `machine_id`、`slot_index` | `POST /machines/{id}/slots/{index}/clear-error` | medium |
| `dispatch` | 上方案：把已发布版本装到机台，不开始测试 | `plan_id`、`version`、`machine_ids` | 下发已发布方案 | medium |
| `production_precheck` | 只做下发前检查，不执行 | 同 `production_start` | `POST /production/precheck` | low |
| `production_start` | 开始连续生产；批准前自动预检 | `machine_ids`、`plan_id`、`plan_version`、`batch_id` 或 `serial_numbers`（二选一）、`auto_recover?`、`max_count?` | `POST /production/start` | medium |
| `production_stop` | 停止连续生产；不给批次时停止当前生产 | `batch_id?` | `POST /production/stop` | high |
| `sim_speed` | 改仿真倍率。必须给出 `machine_ids`，只缩短等待，不改变温度曲线 | `speed`、`machine_ids` | `PUT /sim/clock` | medium |
| `sim_scenario` | 对某台应用预设场景 | `name`、`machine_id` | `POST /sim/scenarios/{name}/apply` | high |
| `sim_fault` | 注入故障 | `machine_id`、`kind`、`slot_index?` | `POST /sim/faults` | high |
| `suggest_compensation` | 提交补偿建议，不改读数 | `machine_id`、`channel`、`proposed_delta` | 补偿建议接口 | low |
| `apply_compensation` | 写入通道补偿，只影响之后的新测试。批准时展示「当前值 → 新值」 | `machine_id`、`mode`、`items[{channel, value}]`，或 `suggestion_id` + `confirmed_delta` | `PUT /machines/{id}/compensation` | medium |

约定：

- 多台操作由 MCP 逐台调用。全部失败时返回第一台的错误码；部分失败时 `ok=false`、`error.code=PARTIAL`，`detail.done` 和 `detail.failed` 分开列。已经成功的不要再发。
- 批准前的 `effects` 会列出实际影响，例如关机前列出哪些槽正在测试、复位前列出哪些机台处于故障。
- `sim_*` 在数据源不是仿真时直接返回失败，说明当前不是仿真数据源。场景名和故障种类用本工具的 `sim_catalog` 查。
- 槽号从 1 开始，且不能超过该机的 `slot_count`。超出时在批准前就返回 `NOT_FOUND`，不会打到集群。
- 建批次和放回待测不在这个工具里，用 `vc_board`。

### 7.2 `vc_plan` — 测试方案

查询、起草、校验、保存、删除、发布。上到机台用 `vc_machine` 的 `dispatch`。

| action | 功能 | 主要参数 | 后端接口 | 风险 |
| --- | --- | --- | --- | --- |
| `plans` | 方案列表。`draft=true` 只看草稿，`false` 只看已发布 | `q?`、`draft?` | `GET /plans` | low |
| `plan` | 方案详情（指定版本或最新） | `plan_id`、`version?` | `GET /plans/{id}` | low |
| `from_text` | 把自然语言整理成方案草稿 | `text` | `POST /plan-drafts/from-text` | low |
| `validate` | 校验方案参数，返回逐项问题 | `plan` | `POST /plans/validate` | low |
| `save_draft` | 保存草稿；带 `plan_id` 为更新 | `plan`、`plan_id?` | `POST /plan-drafts` / `PUT /plan-drafts/{id}` | low |
| `delete_draft` | 删除草稿 | `plan_id` | `DELETE /plan-drafts/{id}` | medium |
| `publish` | 发布为新版本；批准前自动校验。不会自动装到机台 | `plan`、`plan_id?` | `POST /plans` | medium |

`plan` 对象字段：`name, start_temp_c, duration_s, sample_period_s, power_w, force_g, orientation, overtemp_c, ambient_low_c, ambient_high_c, limits[{item, low, high, unit, skipped}]`。时长 1–600 秒，功率 0.1–10 W，压紧力 20–300 g。判定项温差写成 `Temp_T0-T1`。2.5 W 常配 100 g，3.5 W 常配 120 g。

### 7.3 `vc_board` — 板子和批次

拉新是 `create_batch`，不是单独的工具。

| action | 功能 | 主要参数 | 后端接口 | 风险 |
| --- | --- | --- | --- | --- |
| `boards` | 查板。没有等级、单板缺陷和真实热阻 | `model?`、`batch_id?`、`board_state?`（`NEW` / `IN_MACHINE` / `TESTED`）、`golden?` | `GET` 板子列表 | low |
| `board` | 按序列号看一片板 | `serial_number` | `GET` 单板 | low |
| `batches` | 批次统计。这里的缺陷比例是建批设定，不是测试良率 | `model?`、`state?`、`q?`、`cursor`、`limit` | `GET /batch-stats` | low |
| `batch` | 单个批次统计 | `batch_id` | `GET /batch-stats/{id}` | low |
| `models` | 型号目录与参考功率 | — | `GET /models` | low |
| `defect_kinds` | 缺陷种类目录，不能据此判断某一片板有没有缺陷 | — | 缺陷目录 | low |
| `create_batch` | 拉新：生成一批待测板。片数和良率可以指定，也可以在区间里随机 | `model`、`count` 或 `count_min`/`count_max`、`yield_rate` 或 `defect_ratio` | `POST /batches` | medium |
| `requeue` | 把已测完的标准样品放回待测。普通板会被拒绝 | `serial_number` | `POST /products/{serial}/requeue` | medium |

良率只按 `vc_run` 的测试记录计算，不用批次的缺陷比例。

### 7.4 `vc_run` — 测试记录

只查不改。

| action | 功能 | 主要参数 | 后端接口 |
| --- | --- | --- | --- |
| `runs` | 测试记录列表 | `machine_id?`、`batch_id?`、`passed?`、`status?`、`q?`、`window` / `from_ms`/`to_ms`、`cursor`、`limit` | `GET /runs` |
| `run` | 单条记录：判定项、失败项；`detail=true` 用 `since` 和 `limit` 续读采样 | `run_id` | `GET /runs/{id}`（+ `/samples`） |
| `ground_truth` | 仿真真值，只在用户要核对物理答案时用 | `run_id` | `GET /runs/{id}/ground-truth` |
| `compare` | 聚合：2–5 个批次的良率、失败项分布、各机台良率。不给批次时取指定型号最近 3 个 | `batch_ids?`、`model?` | `GET /batch-stats` + `GET /reports/data` |
| `trend` | 产出与良率、异常分类、机台 Rc 偏差 | `metric`：`output` \| `anomaly` \| `rc_bias`，`window` | `GET /stats/agg5m`、`/stats/anomaly-trend`、`/stats/rc-bias` |
| `export` | 导出已完成且保留结果的生产 CSV。表头三行是列名、上限、下限 | `limits_plan_id`、`version?` | 生产 CSV 导出 | 

读数里 `99999` 和 `9999` 表示接触不良，`-1` 表示采集无应答，`-2` 表示回答无法解析。60 秒附近的快照不参与合格判定。

### 7.5 `vc_alarm` — 告警

| action | 功能 | 主要参数 | 后端接口 | 风险 |
| --- | --- | --- | --- | --- |
| `alarms` | 告警列表 | `acked?`、`machine_id?`、`level?`、`cursor`、`limit` | `GET /alarms` | low |
| `attribution` | 某条告警的归因结论 | `alarm_id` | `GET /alarms/{id}/attribution` | low |
| `ack` | 确认告警 | `alarm_ids` | `POST /alarms/{id}/ack` | low |
| `unack` | 取消确认 | `alarm_ids` | `POST /alarms/{id}/unack` | low |
| `ack_all` | 确认全部未确认告警 | — | `POST /alarms/ack-all` | medium |
| `rerun_attribution` | 重新归因 | `alarm_id` | `POST /alarms/{id}/attribution` | low |

### 7.6 `vc_report` — 测试报告

| action | 功能 | 主要参数 | 后端接口 | 风险 |
| --- | --- | --- | --- | --- |
| `report_summary` | 生成批次报告结论 | `batch_ids` | `POST /reports/summary` | low |
| `report_figure` | 按描述生成图表，返回 `figure_id`。只给 `figure_id` 时查进度 | `batch_ids`、`prompt` 或 `figure_id` | `POST /reports/figures`、`GET /reports/figures/{id}` | low |
| `report_export` | 导出 PDF | `batch_ids`、`figure_ids?`、`summary_lines?` | `POST /reports/export` | medium |

## 8. 后端 Agent 怎么用

Agent 只允许调用这 6 个工具：

`mcp__vc-testos__vc_machine`、`vc_plan`、`vc_board`、`vc_run`、`vc_alarm`、`vc_report`。

1. 系统提示词按实体列出 action。启停、拉新、上方案都写在对应工具的 `action` 上，不教模型去找旧的 `vc_line`、`vc_data`、`vc_operate`、`vc_quality`。
2. 待确认操作识别 MCP 返回的 `APPROVAL_REQUIRED`。页面卡片用 `sentence` 和 `effects`，不展示原始参数 JSON。
3. 批准接口用 `MCP_APPROVAL_SECRET` 计算 `approval` 后，只带 `action`、`confirm_id`、`approval` 回调同一个工具。
4. 调用 MCP 时在请求头放入当前用户的 JWT。

## 9. 目录结构

```
mcp_server/
├── DESIGN.md
├── README.md
├── requirements.txt
├── .env.example           # VC_API_BASE、VC_TENANT、VC_USERNAME、VC_PASSWORD、MCP_PORT=8100、MCP_APPROVAL_SECRET、REDIS_URL
├── app/
│   ├── main.py            # FastAPI 挂载 MCP，/health
│   ├── server.py          # 注册 6 个工具；只读模式拦截写 action
│   ├── config.py
│   ├── identity.py        # 从请求头判断用户模式 / 只读模式
│   ├── backend.py         # 调后端 /api/v1：令牌、超时、错误码映射、Idempotency-Key
│   ├── approval.py        # 按 (工具, action) 定风险；confirm_id 登记、HMAC 校验、一次性消费
│   ├── result.py          # ok / fail / need_approval 统一返回
│   ├── text.py            # 中文 summary 拼装
│   └── tools/
│       ├── machine.py     # 公开 vc_machine
│       ├── plan.py        # 公开 vc_plan
│       ├── board.py       # 公开 vc_board
│       ├── run.py         # 公开 vc_run
│       ├── alarm.py       # 公开 vc_alarm
│       ├── report.py      # 公开 vc_report
│       ├── line.py        # 未注册，机台和告警的查询实现
│       ├── data.py        # 未注册，方案、板子、记录、补偿的查询实现
│       ├── operate.py     # 未注册，run_operate：机台写动作和拉新
│       └── quality.py     # 未注册，run_quality：告警写动作、补偿和报告
└── tests/
```
