/**
 * 数据模型：集群侧字段与 mockcluster OpenAPI 保持同名（snake_case），
 * 平台本地扩展的字段放在 Local* 类型里，由我们自己的后端落库后提供。
 */

/* ---------- 集群侧（GET /api/fleet、/api/machines/{id} ...） ---------- */
export type MachineStatus = 'CREATED' | 'OFFLINE' | 'STARTING' | 'INITIALIZING' | 'READY' | 'FAULT' | 'MAINTENANCE' | 'STOPPED'
export type CommStatus = 'ONLINE' | 'DEGRADED' | 'DISCONNECTED'
export type SlotPhase = 'IDLE' | 'RESETTING' | 'PREHEATING' | 'WAITING_LOAD' | 'CLAMPING' | 'SAMPLING' | 'RECOVERING' | 'ERROR' | 'COMPLETED'
export type RunStatus = 'RUNNING' | 'COMPLETED' | 'ABORTED' | 'FAULT'
export type PlcKind = 'INOVANCE' | 'OMRON'
export type DriftKind = 'FIXED' | 'LINEAR' | 'RANDOM_WALK' | 'STEP' | 'HOURLY'
export type TruthLabel = 'INVALID_TEST' | 'EQUIPMENT_ANOMALY' | 'PRODUCT_DEFECT' | 'DATA_ANOMALY' | 'ENVIRONMENT_ANOMALY' | 'SUSPECT' | 'NORMAL'

export interface ChannelValue { channel: string; value: number }

export interface Capability {
  temp_channels: string[]
  force_channels: string[]
  duration_low_s: number
  duration_high_s: number
  power_low_w: number
  power_high_w: number
  force_low_g: number
  force_high_g: number
}

/** SlotViewOut 的子集 + 本地计算的进度 */
export interface Slot {
  index: number
  phase: SlotPhase
  serial_number: string | null
  tests_done: number
  last_error: string
  power_w: number
  vacuum_kpa: number
  /** 当前 T0 / T1 / Ta，取自 temps */
  t0: number
  t1: number
  ta: number
  /** 当前采样 t_s 与方案 duration_s 之比，前端展示用 */
  progress: number
  run_id: string | null
}

export interface Machine {
  machine_id: string
  serial: string
  fixture: string
  holder: string
  thermal_boards: string
  plc: PlcKind
  firmware: string
  slot_count: number
  status: MachineStatus
  comm_status: CommStatus
  comm_note: string
  speed: number
  room_temp_c: number
  alarm: string
  plan_id: string | null
  plan_version: number | null
  capability: Capability
  slots: Slot[]
  yield_recent?: { n: number; passed: number }
}

export interface LimitRule {
  item: string
  low: number | null
  high: number | null
  unit: string
  skipped: boolean
}

/** POST /api/plans 的请求体 / PlanOut */
export interface Plan {
  plan_id: string
  name: string
  version: number
  start_temp_c: number
  duration_s: number
  sample_period_s: number
  power_w: number
  force_g: number
  orientation: number
  overtemp_c: number
  ambient_low_c: number
  ambient_high_c: number
  limits: LimitRule[]
}

export interface ProductModel { model: string; resistance_mean: number; resistance_sd: number; power_w: number }

export interface Batch { batch_id: string; model: string; count: number; defect_ratio: number; batch_factor: number; remaining?: number }

export interface Run {
  run_id: string
  machine_id: string
  slot_index: number
  serial_number: string
  plan_id: string
  plan_version: number
  status: RunStatus
  passed: boolean | null
  fail_items: string[]
  keep_result: boolean
  /** 本地从 result.deltas 抽取的关键量 */
  rc: number | null
  dt01: number | null
  batch_id?: string
  ended_at: number
}

export interface Drift { drift_id: string; machine_id: string; channel: string; kind: DriftKind; value: number; step_at: number; current: number }

export interface FaultInfo { kind: string; layer: 'fixture' | 'actuator' | 'sensor' | 'environment' | 'communication' | 'plc'; alarms: boolean }

/* ---------- 平台本地（我们的后端提供） ---------- */
export type AlarmLevel = 'critical' | 'major' | 'minor'
export type AlarmSource = '机台' | '槽位' | '通信' | '判定' | '漂移' | '数据'

export interface Alarm {
  id: string
  time: number
  level: AlarmLevel
  machine_id: string
  slot_index?: number
  source: AlarmSource
  /** 对应集群的报警原因 / 故障种类 / 判定项 */
  code: string
  message: string
  acked: boolean
}

/** 本地批次执行统计（由 runs 聚合） */
export interface BatchStat {
  batch_id: string
  model: string
  count: number
  tested: number
  passed: number
  failed: number
  aborted: number
  plan_id: string
  plan_version: number
  machine_ids: string[]
  started_at: number
  ended_at: number | null
  state: 'running' | 'done' | 'stopped'
  rc_mean: number
  rc_sd: number
  top_fail: string
  eta_s?: number | null
}

/** 5 分钟聚合（TimescaleDB 连续聚合 agg_5m） */
export interface Agg5m {
  bucket: number
  tests: number
  passed: number
  failed: number
  aborted: number
  rc_mean: number
  dt01_mean: number
}

/** 方案在本地的元信息：草稿不推送到集群，发布即 POST /api/plans 生成新版本 */
export interface PlanMeta {
  plan_id: string
  versions: number[]
  updated_at: number
  author: string
  source: 'agent' | 'manual'
  draft: boolean
}

export type AiModule = 'agent.analysis' | 'agent.plan' | 'agent.ops' | 'report' | 'anomaly' | 'calib'
