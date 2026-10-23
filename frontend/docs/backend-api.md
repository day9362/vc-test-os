# VC-TestOS 后端接口要求

> 面向后端工程师。本文列出前端需要后端提供的全部接口，以及字段、行为和错误约定。
> 前端当前使用 `src/mock/cluster.ts` 的模拟数据，类型定义见 `src/api/types.ts`；后端返回结构应与之保持一致，方便直接替换。

---

## 0. 总体约定

### 0.1 架构边界

```
前端  ──HTTP / WebSocket──>  本平台后端  ──HTTP──>  真实集群 或 仿真平台（mockcluster）
                                 │
                                 ├── 本地数据库（时序 + 关系）
                                 └── LLM 网关
```

- **前端只访问本平台后端，不直接访问集群。** 集群地址、令牌只保存在后端。
- 集群侧字段（机台、槽位、方案、测试记录等）**沿用 mockcluster 的字段名**（snake_case），不要二次改名。
- 所有对设备的写操作（上电、关机、维修、复位、下发、补偿、开始/停止生产）都由后端转调集群 API，并**写审计日志**。
- AI 不得直接调用写操作。本文中的 AI 接口只产出草稿、建议、总结和图表，落到设备上的动作都由用户在页面上手动触发。

### 0.2 基础

| 项 | 约定 |
|---|---|
| 前缀 | `/api/v1` |
| 格式 | `application/json; charset=utf-8` |
| 时间 | Unix 毫秒时间戳（number），字段名以 `_at` 结尾或为 `time` / `ts` / `bucket` |
| 温度 / 功率 / 压力 | ℃ / W / g，数值不带单位 |
| 认证 | `Authorization: Bearer <token>`；`GET /api/v1/me` 返回当前用户与角色 |
| 分页 | 游标分页：请求 `cursor`、`limit`（默认 50，最大 500），响应 `{ items, next_cursor }`，`next_cursor` 为 `null` 表示没有更多 |

### 0.3 错误格式

非 2xx 响应统一为：

```json
{ "error": { "code": "MACHINE_DISCONNECTED", "message": "M12 通信断开，集群返回 503", "detail": {} } }
```

| HTTP | code | 场景 |
|---|---|---|
| 400 | `BAD_REQUEST` | 参数格式错误 |
| 401 / 403 | `UNAUTHORIZED` / `FORBIDDEN` | 未登录 / 角色无权限 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `CONFLICT` | 状态冲突，如机台不在可操作状态、批次已在生产中 |
| 422 | `VALIDATION_ERROR` | 业务校验失败，`detail.issues` 为 `[{ field, message }]` |
| 502 | `CLUSTER_ERROR` | 集群返回错误，`detail.upstream` 附原始响应 |
| 503 | `MACHINE_DISCONNECTED` | 目标机台 `comm_status = DISCONNECTED` |
| 504 | `CLUSTER_TIMEOUT` | 请求集群超时 |

### 0.4 写操作通用要求

- 请求头带 `Idempotency-Key`（前端生成 UUID），后端 10 分钟内去重，防止重复点击导致重复下发。
- 响应里带 `audit_id`，对应审计日志的一条记录。
- 写操作完成后，相关状态变化要通过 WebSocket 推送（见第 1 节），前端不再轮询。

---

## 1. 实时推送（WebSocket）

`GET /api/v1/ws`，升级为 WebSocket。连接后客户端发送订阅：

```json
{ "op": "subscribe", "topics": ["fleet", "slots", "runs", "alarms", "agg_5m", "batches"] }
```

服务端消息统一为 `{ "topic": string, "ts": number, "data": ... }`：

| topic | 触发时机 | data |
|---|---|---|
| `fleet` | 机台状态、通信状态、报警、装载方案变化 | `MachineSummary[]`（只含有变化的机台） |
| `slots` | 槽位步骤或读数变化；采样中的槽位按 1–2 s 推送 | `{ machine_id, slots: Slot[] }` |
| `runs` | 一片测试结束（COMPLETED / ABORTED / FAULT） | `Run` |
| `alarms` | 新告警、告警被确认或撤销确认 | `Alarm` |
| `agg_5m` | 当前 5 分钟桶更新或新桶生成 | `Agg5m` |
| `batches` | 批次进度变化、开始、停止、完成 | `BatchStat` |
| `production` | 连续生产状态变化 | `Production \| null` |
要求：
- 心跳：服务端每 15 s 发送 `{ "topic": "ping" }`，客户端 30 s 收不到即重连。
- 重连后客户端会重新拉一次快照接口（第 2–4 节），推送不需要补发历史。
- 前端「暂停实时刷新」只是本地暂停渲染，后端无需处理。

---

## 2. 机台与槽位

### 2.1 数据结构

```ts
type MachineStatus = 'CREATED' | 'OFFLINE' | 'STARTING' | 'INITIALIZING' | 'READY' | 'FAULT' | 'MAINTENANCE' | 'STOPPED'
type CommStatus = 'ONLINE' | 'DEGRADED' | 'DISCONNECTED'
type SlotPhase = 'IDLE' | 'RESETTING' | 'PREHEATING' | 'WAITING_LOAD' | 'CLAMPING' | 'SAMPLING' | 'RECOVERING' | 'ERROR' | 'COMPLETED'

interface Machine {
  machine_id: string          // "M01"
  serial: string              // "X9610_1#"
  fixture: string
  holder: string
  thermal_boards: string
  plc: 'INOVANCE' | 'OMRON'
  firmware: string
  slot_count: number
  status: MachineStatus
  comm_status: CommStatus
  comm_note: string           // 降级原因，如 "丢包"
  speed: number               // 仿真倍率；真实集群固定 1
  room_temp_c: number
  alarm: string               // 当前报警，"PLC_FAULT · PLC 无响应"；无则 ""
  plan_id: string | null      // 当前装载方案
  plan_version: number | null
  capability: Capability
  slots: Slot[]
  last_sync_at: number        // 本地最后一次成功同步该机台的时间（断开时前端用来提示数据陈旧）
  yield_recent: { n: number; passed: number }   // 最近 400 片的判定统计（运行总览机台卡片用）
}

interface Capability {
  temp_channels: string[]     // T0–T14, Ta, T_air, T_motor_up, T_motor_down
  force_channels: string[]    // F1–F14
  duration_low_s: number; duration_high_s: number
  power_low_w: number; power_high_w: number
  force_low_g: number; force_high_g: number
}

interface Slot {
  index: number               // 1 起
  phase: SlotPhase
  serial_number: string | null
  tests_done: number
  last_error: string
  power_w: number
  vacuum_kpa: number
  t0: number; t1: number; ta: number   // 当前读数（取自 temps）
  progress: number            // 0–100，= 当前 t_s / 方案 duration_s；非采样时为 0
  run_id: string | null
}
```

`MachineSummary` = `Machine` 去掉 `capability` 和 `slots`。

### 2.2 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/machines` | 全部机台，含 `slots`。运行总览、设备配置列表、新建测试任务的机台选择都用它 |
| GET | `/machines/{id}` | 单台详情 |
| GET | `/machines/{id}/slots/{index}/curve` | 该槽位当前（或最近一次）测试的过程曲线，见下 |
| POST | `/machines/{id}/power-on` | 上电 |
| POST | `/machines/{id}/power-off` | 关机 |
| POST | `/machines/{id}/maintenance` | body `{ "on": boolean }`，进入 / 结束维修 |
| POST | `/machines/{id}/reset` | 复位：清除 FAULT，ERROR 槽位回到 IDLE |
| GET | `/machines/{id}/plan-history` | 该机台用过的方案，见 2.3 |

槽位曲线响应：

```json
{
  "run_id": "R-M01-4-d2460bc5bd",
  "plan_id": "PLAN-592bbc46", "plan_version": 2, "duration_s": 180,
  "points": [ { "t_s": 0, "T0": 45.0, "T1": 24.4, "Ta": 24.0, "power_w": 2.5 } ],
  "deltas": { "Temp_T0-T1": 2.07, "Rc": 4.77 }
}
```

- 支持 `?since=<t_s>` 增量拉取。
- 读数为哨兵值时**原样返回**（99999 / 9999 = 接触不良，-1 = 板卡无响应，-2 = 无法解析），前端负责标记显示。

设备操作的行为要求：
- 机台 `DISCONNECTED` 时直接返回 503 `MACHINE_DISCONNECTED`，不要转发给集群。
- 关机或进入维修时，如果有槽位正在 SAMPLING，前端会二次确认；后端照常执行，被中止的测试记为 `ABORTED`。

### 2.3 方案记录（本地 plan_dispatch 表）

`GET /machines/{id}/plan-history`

```json
{ "items": [ { "plan_id": "PLAN-592bbc46", "name": "45度测3分钟", "version": 2, "from": 1759800000000, "to": null, "runs": 412 } ] }
```

- `to = null` 表示当前装载。
- 每次给机台下发方案（`PUT /machines/{id}/plan` 或开始生产时自动下发）都要记一条。

---

## 3. 运行总览统计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/stats/kpi?range=shift` | 顶部 KPI，`range` 取 `shift`（本班 8 h）或 `2h` |
| GET | `/stats/agg5m?from=&to=` | 5 分钟汇总序列（产出与良率图、汇总表） |
| GET | `/stats/anomaly-trend?hours=8` | 按小时、按类别统计的异常数 |
| GET | `/stats/rc-bias` | 各机台 Rc 相对全线中位数的偏差 |
| GET | `/stats/pipeline` | 顶部流程条各环节的状态文字 |

`/stats/kpi`：

```json
{
  "online": 11, "total": 12,
  "busy_slots": 89, "error_slots": 3, "slot_total": 120,
  "tests": 5332, "yield_rate": 97.36, "rc_mean": 4.847,
  "open_alarms": 4, "critical_alarms": 2,
  "prev": { "tests": 5122, "yield_rate": 97.66 }
}
```

- `prev` 是上一班同口径数据，用来算环比。
- `rc_mean` 取最近 120 片有效结果。

`Agg5m`（来自连续聚合表 `agg_5m`）：

```ts
interface Agg5m { bucket: number; tests: number; passed: number; failed: number; aborted: number; rc_mean: number; dt01_mean: number }
```

`/stats/anomaly-trend`：

```json
{ "hours": [1759820400000], "series": { "equipment": [1], "product": [6], "communication": [0], "data": [1] } }
```

类别映射：`equipment` = 设备异常（含漂移超阈值），`product` = 产品缺陷（判定不合格），`communication` = 通信，`data` = 数据异常（哨兵值等）。

`/stats/rc-bias`：

```json
{ "median": 4.80, "items": [ { "machine_id": "M07", "bias": 0.094 } ] }
```

---

## 4. 告警

```ts
interface Alarm {
  id: string
  time: number
  level: 'critical' | 'major' | 'minor'
  machine_id: string
  slot_index?: number
  source: '机台' | '槽位' | '通信' | '判定' | '漂移' | '数据'
  code: string          // 集群报警原因 / 故障种类 / 判定项，如 PLC_FAULT、VACUUM_LEAK、Temp_T0-T1
  message: string
  acked: boolean
  acked_by?: string; acked_at?: number
}
```

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/alarms?acked=false&machine_id=&level=&cursor=&limit=` | 列表，按时间倒序 |
| POST | `/alarms/{id}/ack` | 确认 |
| POST | `/alarms/{id}/unack` | 撤销确认（前端 toast 里的「撤销」按钮） |
| POST | `/alarms/ack-all` | 全部确认 |
| GET | `/alarms/{id}/attribution` | AI 异常归因结果（AI 模块 `anomaly`），见下 |
| POST | `/alarms/{id}/attribution` | 重新归因（用户手动触发） |

异常归因由后端在新告警产生时自动执行，结果存库，前端只读取：

```json
{
  "alarm_id": "AL-10418",
  "status": "pending | done | failed",
  "category": "equipment | product | communication | data | environment",
  "confidence": 0.86,
  "summary": "M07 T1 通道线性漂移 +0.18 ℃，同批次在其它机台正常，判断为设备异常",
  "evidence": [ "同批次其它 6 台良率 98.1%，M07 为 95.4%", "标准样品复测 T1 偏差 +0.182 ℃" ],
  "suggestion": "写入 T1 补偿 −0.18 ℃ 后用标准样品复测",
  "model": "deepseek-v3", "created_at": 1759834000000
}
```

- `category` 与第 3 节异常趋势的类别一致，归因完成后计入对应类别。
- `suggestion` 只是文字建议，不附带可执行操作。

告警由后端生成，至少覆盖：
- 机台进入 FAULT
- 通信 DISCONNECTED / DEGRADED（DEGRADED 是否告警由设置 `rules.degraded_alarm` 控制）
- 槽位进入 ERROR
- 通道漂移估计超过 `rules.drift_c`（记为 `EQUIPMENT_ANOMALY`）
- 连续不合格
- 哨兵值
- 房间温度超出方案范围

---

## 5. 测试方案

### 5.1 数据结构（与集群 `CreatePlanIn` / `PlanOut` 一致）

```ts
interface LimitRule { item: string; low: number | null; high: number | null; unit: string; skipped: boolean }
interface Plan {
  plan_id: string; name: string; version: number    // 草稿 version = 0
  start_temp_c: number; duration_s: number; sample_period_s: number
  power_w: number; force_g: number; orientation: number   // 0 / 90 / 180 / 270
  overtemp_c: number; ambient_low_c: number; ambient_high_c: number
  limits: LimitRule[]
}
interface PlanMeta { plan_id: string; versions: number[]; updated_at: number; author: string; source: 'agent' | 'manual'; draft: boolean }
```

判定项 `item` 可选值：`Temp_Ta`、`Temp_T0-T1`、`Temp_T1-T2` … `Temp_T1-T14`、`F1` … `F14`、`power_w`。

### 5.2 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/plans` | 已发布方案（最新版本）+ 本地草稿，每项为 `{ plan: Plan, meta: PlanMeta }` |
| GET | `/plans/{plan_id}?version=` | 指定版本；不传则最新 |
| POST | `/plans/validate` | body 为 Plan（不含 `plan_id` / `version`），返回校验结果，见下 |
| POST | `/plans` | **发布**：后端校验后转调集群 `POST /api/plans`。同名会生成新版本，返回 `{ plan_id, version }` |
| POST | `/plan-drafts` | 新建草稿（复制为草稿也走这里），只存本地 |
| PUT | `/plan-drafts/{id}` | 更新草稿 |
| DELETE | `/plan-drafts/{id}` | 删除草稿 |
| POST | `/plan-drafts/from-text` | 自然语言起草（AI 模块 `agent.plan`），见下 |

`/plans/validate` 响应（前端「发布前校验」直接渲染）：

```json
{
  "ok": false,
  "issues": [
    { "level": "danger", "field": "power_w", "message": "加热功率 3.5 W 不在 power_w 判定范围内" },
    { "level": "warn", "field": "overtemp_c", "message": "超温保护距离起始温度不足 10 ℃，可能误触发" },
    { "level": "ok", "message": "功率与 HVP1307G17-1 的参考功率一致" }
  ]
}
```

至少要做这些校验：
- 各字段在机台 `capability` 范围内
- `ambient_low_c < ambient_high_c`
- 每个判定项 `low < high`
- 判定项不重复
- 加热功率落在 `power_w` 判定范围内
- 功率与已登记型号的参考功率是否匹配（给出 warn 或 ok）

`/plan-drafts/from-text`：

```json
// 请求
{ "text": "HVP 3.5W，压紧力 120g，测 3 分钟，T0-T1 不超过 3.4 度" }
// 响应
{ "plan": { "...": "Plan，version = 0" }, "meta": { "...": "PlanMeta，source = agent" }, "notes": ["压紧力未说明，按该功率的常用配置填写"], "usage": { "input": 3800, "output": 900 } }
```

`notes` 用来说明 AI 补了哪些默认值、做了哪些推断，前端显示在草稿下方。

---

## 6. 型号、批次与连续生产

### 6.1 数据结构

```ts
interface ProductModel { model: string; resistance_mean: number; resistance_sd: number; power_w: number }
interface Batch { batch_id: string; model: string; count: number; defect_ratio: number; batch_factor: number; remaining: number }  // remaining = 状态为 NEW 的片数
interface BatchStat {
  batch_id: string; model: string; count: number
  tested: number; passed: number; failed: number; aborted: number
  plan_id: string; plan_version: number; machine_ids: string[]
  started_at: number; ended_at: number | null
  state: 'running' | 'done' | 'stopped'
  rc_mean: number; rc_sd: number; top_fail: string
  eta_s: number | null          // 预计剩余秒数，后端按实际节拍估算
}
interface Production { batch_id: string; queue_remaining: number; plan_id: string; plan_version: number }
```

### 6.2 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/models` | 型号列表 |
| GET | `/batches` | 已到料的批次，含 `remaining`（新建测试任务的批次下拉） |
| GET | `/batch-stats?state=&model=&q=&cursor=` | 批次执行统计（执行中、历史批次） |
| GET | `/batch-stats/{batch_id}` | 单个批次统计 |
| GET | `/production` | 当前连续生产状态，没有则返回 `null` |
| POST | `/production/precheck` | 下发前校验，body 同 start，返回同 `/plans/validate` 的结构 |
| POST | `/production/start` | 开始连续生产，转调集群 `POST /api/fleet/production/start` |
| POST | `/production/stop` | 停止，body `{ "batch_id": string }`，转调集群 `/production/stop` |

`/production/start` 请求体（字段与集群一致）：

```json
{
  "machine_ids": ["M01", "M02"],
  "plan_id": "PLAN-3f2c71d0", "plan_version": 3,
  "batch_id": "B-HVP1307G17-1-9725e9b1",
  "serial_numbers": null,
  "auto_recover": true,
  "max_count": null
}
```

- `batch_id` 和 `serial_numbers` 二选一。
- 响应：`{ "batch_id", "accepted": ["M01"], "skipped": [{ "machine_id": "M02", "reason": "正在测量且方案不同" }], "audit_id" }`。被集群跳过的机台必须在 `skipped` 里说明原因。
- 关机的机台由集群自动上电；方案版本不一致的机台由集群自动下发。后端都要记入 plan_dispatch。

`precheck` 至少要检查：
- 方案功率是否等于型号参考功率（不一致为 danger）
- 方案是否有 `power_w` 判定项
- 所选批次 `remaining > 0`
- 所选机台中有没有 DISCONNECTED、MAINTENANCE 或 FAULT 的（danger）
- 有没有机台正在测量其它方案、会被跳过（warn）
- 仿真倍率过低时给出提示（warn，仅仿真模式）

---

## 7. 测试记录

```ts
interface Run {
  run_id: string; machine_id: string; slot_index: number; serial_number: string
  plan_id: string; plan_version: number
  status: 'RUNNING' | 'COMPLETED' | 'ABORTED' | 'FAULT'
  passed: boolean | null        // 非 COMPLETED 时为 null
  fail_items: string[]
  keep_result: boolean
  rc: number | null             // 从 result.deltas 抽取
  dt01: number | null           // Temp_T0-T1
  batch_id: string
  ended_at: number
}
```

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/runs?machine_id=&batch_id=&passed=&status=&q=&from=&to=&cursor=&limit=` | 列表。`passed` 取 `true` / `false` / `null`（null = 中止或故障）；`q` 模糊匹配 `run_id` 和序列号 |
| GET | `/runs/{run_id}` | 详情，含完整 `result`（所有 `deltas`、各判定项实测值） |
| GET | `/runs/{run_id}/samples?since=` | 过程曲线，按 `seq` 增量 |
| GET | `/runs/{run_id}/ground-truth` | **仅仿真模式且设置里打开 `sim.use_ground_truth` 时可用**，否则 404；只用于算法评估 |
| GET | `/export/production.csv?batch_id=&from=&to=` | 导出生产结果表 |

---

## 8. 批次报告

报告支持单批次和多批次合并，前端路由为 `/report?b=id1,id2`。

### 8.1 报告数据

`GET /reports/data?batch_ids=B-a,B-b`

```json
{
  "batches": ["BatchStat ..."],
  "summary": { "tested": 1887, "passed": 1786, "failed": 89, "aborted": 12, "yield_rate": 94.65, "rc_mean": 4.909, "rc_sd": 0.287, "cpk_t01": 0.96, "usl_t01": 2.8, "machine_count": 9 },
  "machine_yield": [ { "machine_id": "M01", "n": 210, "passed": 200 } ],
  "rc_histogram": { "edges": [4.17, 4.23], "counts": { "B-a": [3], "B-b": [1] } },
  "fail_pareto": [ { "item": "Temp_T1-T14", "count": 36 } ],
  "delta_profile": {
    "items": ["T1-T2", "T1-T14"],
    "mean": { "B-a": [1.2, 3.3] },
    "p95": [1.4, 3.6],
    "limit": [4.0, null]
  },
  "compare": [ { "batch_id": "B-a", "yield_rate": 96.9, "rc_mean": 4.775 } ]
}
```

- 进行中的批次也可以出报告，数据截止到当前。
- `tested = 0` 的批次不参与计算。
- `p95` 只在单批次时返回。
- `limit` 中 `null` 表示该判定项被跳过。

### 8.2 AI 总结

`POST /reports/summary`，body `{ "batch_ids": [...] }`，AI 模块为 `report`：

```json
{ "lines": ["共 4 个批次、1887 片，合并良率 94.65% ……"], "model": "deepseek-v3", "usage": { "input": 21000, "output": 3200 } }
```

要求：总结里出现的数字必须和 8.1 的计算结果一致（后端把计算结果作为上下文传给模型，不让模型自己算）。

### 8.3 AI 补充分析（计算并生成图表）

用户输入一句分析要求，AI 生成 Python 代码并在沙箱里执行，读取本地库，产出图表和计算结果。这是单次请求、单次结果，不是对话。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/reports/figures` | body `{ "batch_ids": [...], "prompt": "按槽位号画 Rc 箱线图" }`，返回 `{ "figure_id" }`，异步执行 |
| GET | `/reports/figures/{figure_id}` | 查询状态与结果 |
| GET | `/reports/figures?batch_ids=` | 某组批次下已生成的图 |
| DELETE | `/reports/figures/{figure_id}` | 从报告中移除 |
| GET | `/reports/figures/{figure_id}.png` | 下载 PNG |

执行进度通过 SSE 推送：`GET /reports/figures/{figure_id}/events`，每步一个 `{ "step": "在沙箱执行 Python" }` 事件，最后一个事件为 `done`。

`Figure`：

```json
{
  "figure_id": "fig_01", "status": "running | done | failed",
  "prompt": "按槽位号画 Rc 箱线图", "title": "各槽位 Rc 分布",
  "echarts_option": { },
  "png_url": "/api/v1/reports/figures/fig_01.png",
  "code": "df = runs.query(...)\n...",
  "results": [ ["中位数极差", "0.031 ℃/W"], ["结论", "没有显著的槽位效应"] ],
  "usage": { "input": 3000, "output": 1200 },
  "error": null
}
```

- `echarts_option` 和 `png_url` 至少给一个；前端优先用 `echarts_option` 渲染，让图表跟随主题。
- 沙箱只读：只能访问本地库的只读账号，不能联网，不能调用任何写接口。
- 单次执行超时 60 s，超时则 `status = failed`。

### 8.4 导出

`POST /reports/export`，body `{ "batch_ids": [...], "figure_ids": [...], "format": "pdf" }`，返回 `{ "url" }`。报告文件存入对象存储。

---

## 9. 设备一致性与补偿

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/machines/{id}/channel-bias` | 用 10 片 HVP1307G17-1 标准样品复测估计的各通道偏差 |
| GET | `/machines/{id}/compensation` | 当前补偿，转调集群 |
| PUT | `/machines/{id}/compensation` | 写入补偿，body `{ "mode": "add" \| "set", "compensation": [{ "channel": "T1", "value": -0.18 }] }`，转调集群 |
| GET | `/machines/{id}/compensation/suggestion` | 补偿建议（AI 模块 `calib`，也可以是纯规则） |
| GET | `/machines/{id}/compensation/history` | 补偿写入历史（谁、何时、改了什么） |
| GET | `/machines/{id}/drifts` | **仅仿真模式**：注入的漂移，转调集群；真实集群模式返回 `{ "items": [], "supported": false }` |

`channel-bias`：

```json
{ "measured_at": 1759795200000, "golden_model": "HVP1307G17-1", "samples": 10, "threshold_c": 0.15,
  "items": [ { "channel": "T1", "value": 0.182 } ] }
```

`suggestion`：

```json
{ "items": [ { "channel": "T1", "value": -0.182, "reason": "标准样品复测偏差 +0.182 ℃" } ], "basis_at": 1759795200000 }
```

---

## 10. Token 统计

所有 AI 调用都经后端统一转发，每次调用写一条 `ai_calls` 记录。

AI 模块清单（`module` 字段的取值）：

| id | 名称 | 所在页面 | 对应接口 | 触发 |
|---|---|---|---|---|
| `agent.plan` | 方案生成 | 测试方案 | `POST /plan-drafts/from-text` | 用户 |
| `report` | 报告生成 | 批次报告 | `POST /reports/summary`、`POST /reports/figures` | 用户 |
| `anomaly` | 异常归因 | 运行总览 · 告警 | `GET /alarms/{id}/attribution` | 自动 |
| `calib` | 补偿建议 | 设备配置 · 一致性 | `GET /machines/{id}/compensation/suggestion` | 用户 + 自动 |

`agent.analysis`（跨批次分析）和 `agent.ops`（设备操作）属于 Agent 对话，本期不提供接口，但保留这两个模块 id，后续接入时统计口径不变。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ai/modules` | 模块清单：`{ id, name, where, desc, model, trigger }` |
| GET | `/ai/usage/summary?days=30` | 汇总，见下 |
| GET | `/ai/usage/daily?days=30` | 每日按模块的 token 数：`[{ ts, by_module: { "report": 123456 } }]` |
| GET | `/ai/calls?module=&cursor=&limit=` | 调用明细 |

`/ai/usage/summary`：

```json
{
  "days": 30, "total": 30340000, "input": 26290000, "output": 4050000, "calls": 6076, "cost_cny": 115.6,
  "month": { "used": 6940000, "budget": 120000000, "alert_pct": 80 },
  "by_module": [ { "module": "report", "model": "deepseek-v3", "calls": 221, "input": 4600000, "output": 700000, "total": 5300000, "cost_cny": 14.8 } ]
}
```

`ai_calls` 单条：

```json
{ "id": "call-965c08cb", "time": 1759834000000, "module": "anomaly", "user": "系统", "model": "deepseek-v3",
  "input": 2052, "output": 279, "latency_ms": 6500, "ok": true, "ref": { "alarm_id": "AL-10421" } }
```

- 费用按设置里各模型的单价计算。
- 月用量达到 `alert_pct` 时生成一条告警。
- 达到预算 100% 后，自动触发的模块暂停，用户发起的模块仍可用但前端要提示。

---

## 11. 系统设置

### 11.1 设置读写

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/settings` | 读取（敏感字段脱敏，见下） |
| PUT | `/settings` | 整体保存；后端校验后热生效，同步任务在下一个周期使用新频率 |
| POST | `/settings/test-connection` | body `{ "source", "base_url", "token" }`，测试集群连通性 |
| GET | `/sync/jobs/status` | 各同步任务的最近一次运行时间、耗时、是否失败 |

结构（与前端 `src/stores/settings.ts` 一致）：

```ts
interface PlatformSettings {
  source: 'cluster' | 'sim'
  cluster: { base_url: string; token: string; timeout_s: number; retries: number; on_503: 'skip' | 'pause' }
  sim: { base_url: string; speed: number; use_ground_truth: boolean }
  jobs: { key: string; name: string; api: string; interval_s: number; enabled: boolean; note: string }[]
  storage: { dsn: string; samples_days: number; runs_days: number; agg_5m: boolean; object_store: string }
  ai: { base_url: string; api_key: string; monthly_budget_m: number; alert_pct: number; models: Record<AiModule, string> }
  rules: { drift_c: number; we_rules: string[]; sentinel_as_data_anomaly: boolean; degraded_alarm: boolean; ack_timeout_min: number }
}
```

- `cluster.token`、`ai.api_key` 在 GET 时返回掩码（如 `"sk-****9f2a"`）。PUT 时值不变表示不修改。
- `storage.dsn` 中的密码同样脱敏。
- 同步任务的 `key` 固定为：`fleet`、`slots`、`machine`、`runs`、`samples`、`plans`、`batches`、`calib`、`agg`。间隔下限：`slots`、`samples`、`fleet` 为 1 s，其余为 5 s，低于下限返回 422。

`test-connection` 响应：

```json
{ "ok": true, "latency_ms": 62, "machines": 12, "reachable": 11, "server_version": "mockcluster 0.6" }
```

### 11.2 仿真平台专用（`source = sim` 时可用，否则返回 409）

| 方法 | 路径 | 说明 |
|---|---|---|
| PUT | `/sim/clock` | body `{ "speed": 10 }`，转调 `PUT /api/fleet/clock` |
| GET | `/sim/scenarios` | 场景列表：slow_drift、sudden_bias、vacuum_leak、packet_loss |
| POST | `/sim/scenarios/{name}/apply` | body `{ "machine_id" }` |
| GET | `/sim/fault-catalog` | 故障目录，`[{ kind, layer, alarms }]` |
| POST | `/sim/faults` | body `{ "machine_id", "kind", "slot_index"?: number }`，注入故障 |

---

## 12. 其它

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/me` | `{ user_id, name, role: "process" \| "test" \| "quality" \| "admin" }` |
| GET | `/search?q=&limit=10` | 命令面板搜索，返回 `{ machines: [], batches: [], plans: [], runs: [] }`，每项含 `id` 与展示文字 |
| GET | `/audit?actor=&machine_id=&from=&to=&cursor=` | 审计日志：所有写操作，含操作人、来源页面、请求、集群响应 |

---

## 附录 A：前端页面与接口对照

| 页面 | 用到的接口 |
|---|---|
| 运行总览 | `/machines`、`/machines/{id}/slots/{i}/curve`、`/stats/*`、`/alarms`、`/alarms/{id}/attribution`、WS `fleet` `slots` `alarms` `agg_5m` |
| 测试执行 | `/batches`、`/batch-stats`、`/production*`、`/runs`、`/export/production.csv`、`/plans`、WS `runs` `batches` `production` |
| 批次报告 | `/reports/*` |
| 测试方案 | `/plans*`、`/plan-drafts*`（含 `/plan-drafts/from-text`） |
| AI Agent | 本期不提供接口，前端页面保留模拟数据 |
| Token 统计 | `/ai/*`、`/settings`（预算） |
| 设备配置 | `/machines/{id}*`（含补偿建议）、`/alarms?machine_id=`、`/machines/{id}/plan-history` |
| 系统设置 | `/settings*`、`/sync/jobs/status`、`/sim/*` |
| 顶栏 / 命令面板 | `/me`、`/search`、`/alarms?acked=false`、`/settings`（数据源与地址） |

## 附录 B：交付优先级

1. **P0**（前端能跑起来）：第 1 节 WebSocket、第 2 节机台、第 3 节总览统计、第 4 节告警、第 7 节测试记录、第 11.1 节设置
2. **P1**（业务闭环）：第 5 节方案、第 6 节批次与生产、第 9 节补偿、第 8.1 节报告数据
3. **P2**（AI）：第 5 节自然语言起草、第 8.2–8.4 节报告 AI、第 4 节异常归因、第 9 节补偿建议、第 10 节 Token 统计

## 附录 C：本期不包含

- AI Agent 对话：会话管理、流式消息、对话中的工具调用、对话产生的待确认设备操作。后续单独出文档。
