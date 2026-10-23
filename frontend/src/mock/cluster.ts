/* 演示数据：字段与 mockcluster 一致，数值量级取自 cluster.simuoss.cn 的真实返回 */
import type {
  Agg5m, AiModule, Alarm, Batch, BatchStat, Capability, Drift, FaultInfo, Machine, MachineStatus, CommStatus, Plan, PlanMeta, ProductModel, Run, Slot,
} from '@/api/types'

let seed = 20261007
export function rand() {
  seed = (seed * 16807) % 2147483647
  return (seed - 1) / 2147483646
}
export const between = (a: number, b: number) => a + (b - a) * rand()
export const pick = <T>(arr: readonly T[]) => arr[Math.floor(rand() * arr.length)]
export function gauss(mu = 0, sigma = 1) {
  const u = 1 - rand()
  const v = rand()
  return mu + sigma * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}
const hex = () => Math.floor(rand() * 0xffffffff).toString(16).padStart(8, '0')

const now = Date.now()
const MIN = 60_000
const HOUR = 3_600_000

export const TEMP_CHANNELS = ['T0', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'T8', 'T9', 'T10', 'T11', 'T12', 'T13', 'T14', 'Ta', 'T_air', 'T_motor_up', 'T_motor_down']
export const FORCE_CHANNELS = Array.from({ length: 14 }, (_, i) => `F${i + 1}`)
export const LIMIT_ITEMS = ['Temp_Ta', 'Temp_T0-T1', ...Array.from({ length: 13 }, (_, i) => `Temp_T1-T${i + 2}`), ...FORCE_CHANNELS, 'power_w']

export const CAPABILITY: Capability = {
  temp_channels: TEMP_CHANNELS,
  force_channels: FORCE_CHANNELS,
  duration_low_s: 1, duration_high_s: 600,
  power_low_w: 0.1, power_high_w: 10,
  force_low_g: 20, force_high_g: 300,
}

export const SLOT_PHASES = ['RESETTING', 'PREHEATING', 'WAITING_LOAD', 'CLAMPING', 'SAMPLING', 'RECOVERING'] as const
export const PHASE_TEXT: Record<string, string> = {
  IDLE: '空闲', RESETTING: '复位', PREHEATING: '预热', WAITING_LOAD: '上料', CLAMPING: '夹紧', SAMPLING: '采样', RECOVERING: '恢复', ERROR: '错误', COMPLETED: '完成',
}
export const MACHINE_STATUS_TEXT: Record<MachineStatus, string> = {
  CREATED: '已创建', OFFLINE: '关机', STARTING: '上电中', INITIALIZING: '初始化', READY: '就绪', FAULT: '故障', MAINTENANCE: '维修', STOPPED: '已停机',
}
export const COMM_TEXT: Record<CommStatus, string> = { ONLINE: '在线', DEGRADED: '降级', DISCONNECTED: '断开' }

/* ---------- 型号 ---------- */
export const models: ProductModel[] = [
  { model: 'tb158', resistance_mean: 12.05, resistance_sd: 0.3, power_w: 2.5 },
  { model: 'tb172', resistance_mean: 12.35, resistance_sd: 0.3, power_w: 2.5 },
  { model: 'tb179', resistance_mean: 12.5, resistance_sd: 0.3, power_w: 2.5 },
  { model: 'HVP1307G17-1', resistance_mean: 12.2, resistance_sd: 0.3, power_w: 3.5 },
]
/** 测得 Rc 的典型均值（℃/W），用于模拟；真实值来自 result.deltas.Rc */
export const RC_MEAN: Record<string, number> = { tb158: 4.62, tb172: 4.77, tb179: 4.91, 'HVP1307G17-1': 5.18 }

/* ---------- 测试方案 ---------- */
const deltaLimits = (t01: number, t1x: number) => [
  { item: 'Temp_T0-T1', low: 0, high: t01, unit: '℃', skipped: false },
  ...Array.from({ length: 13 }, (_, i) => ({ item: `Temp_T1-T${i + 2}`, low: 0, high: t1x, unit: '℃', skipped: i > 10 })),
]
export const plans: Plan[] = [
  {
    plan_id: 'PLAN-592bbc46', name: '45度测3分钟', version: 2, start_temp_c: 45, duration_s: 180, sample_period_s: 1, power_w: 2.5, force_g: 100, orientation: 0,
    overtemp_c: 80, ambient_low_c: 23, ambient_high_c: 27,
    limits: [...deltaLimits(2.8, 4.0), { item: 'power_w', low: 2.4, high: 2.6, unit: 'W', skipped: false }],
  },
  {
    plan_id: 'PLAN-3f2c71d0', name: 'HVP 3.5W 标准测试', version: 3, start_temp_c: 45, duration_s: 180, sample_period_s: 1, power_w: 3.5, force_g: 120, orientation: 0,
    overtemp_c: 80, ambient_low_c: 23, ambient_high_c: 27,
    limits: [...deltaLimits(3.4, 4.8), { item: 'power_w', low: 3.4, high: 3.6, unit: 'W', skipped: false }],
  },
  {
    plan_id: 'PLAN-a6109ec7', name: '现场观察', version: 4, start_temp_c: 45, duration_s: 10, sample_period_s: 1, power_w: 2.5, force_g: 100, orientation: 90,
    overtemp_c: 80, ambient_low_c: 23, ambient_high_c: 27,
    limits: [{ item: 'power_w', low: 2.4, high: 2.6, unit: 'W', skipped: false }],
  },
  {
    plan_id: 'PLAN-7c04be19', name: 'tb 系列 90° 竖放', version: 1, start_temp_c: 45, duration_s: 240, sample_period_s: 1, power_w: 2.5, force_g: 100, orientation: 90,
    overtemp_c: 80, ambient_low_c: 23, ambient_high_c: 27,
    limits: [...deltaLimits(3.0, 4.2), { item: 'power_w', low: 2.4, high: 2.6, unit: 'W', skipped: false }],
  },
  {
    plan_id: 'DRAFT-0001', name: '高压紧力对比（草稿）', version: 0, start_temp_c: 45, duration_s: 180, sample_period_s: 1, power_w: 2.5, force_g: 160, orientation: 0,
    overtemp_c: 80, ambient_low_c: 23, ambient_high_c: 27,
    limits: [...deltaLimits(2.8, 4.0)],
  },
]
export const planMeta: Record<string, PlanMeta> = {
  'PLAN-592bbc46': { plan_id: 'PLAN-592bbc46', versions: [1, 2], updated_at: now - 26 * HOUR, author: '李工', source: 'manual', draft: false },
  'PLAN-3f2c71d0': { plan_id: 'PLAN-3f2c71d0', versions: [1, 2, 3], updated_at: now - 3 * 24 * HOUR, author: '王工', source: 'agent', draft: false },
  'PLAN-a6109ec7': { plan_id: 'PLAN-a6109ec7', versions: [1, 2, 3, 4], updated_at: now - 6 * 24 * HOUR, author: '周工', source: 'manual', draft: false },
  'PLAN-7c04be19': { plan_id: 'PLAN-7c04be19', versions: [1], updated_at: now - 40 * MIN, author: '李明远', source: 'agent', draft: false },
  'DRAFT-0001': { plan_id: 'DRAFT-0001', versions: [], updated_at: now - 12 * MIN, author: '李明远', source: 'agent', draft: true },
}

/* ---------- 批次 ---------- */
export const batches: Batch[] = [
  { batch_id: `B-tb172-${hex()}`, model: 'tb172', count: 600, defect_ratio: 0.03, batch_factor: 1.0 },
  { batch_id: `B-HVP1307G17-1-${hex()}`, model: 'HVP1307G17-1', count: 240, defect_ratio: 0.03, batch_factor: 1.0 },
  { batch_id: `B-tb158-${hex()}`, model: 'tb158', count: 400, defect_ratio: 0.02, batch_factor: 1.0 },
  { batch_id: `B-tb172-${hex()}`, model: 'tb172', count: 600, defect_ratio: 0.03, batch_factor: 1.0 },
  { batch_id: `B-tb179-${hex()}`, model: 'tb179', count: 300, defect_ratio: 0.08, batch_factor: 1.12 },
  { batch_id: `B-tb172-${hex()}`, model: 'tb172', count: 600, defect_ratio: 0.03, batch_factor: 1.0 },
  { batch_id: `B-tb158-${hex()}`, model: 'tb158', count: 400, defect_ratio: 0.02, batch_factor: 1.0 },
]
const FAILS = ['Temp_T0-T1', 'Temp_T1-T14', 'Temp_T1-T7', 'power_w', 'Temp_T1-T12']
export const batchStats: BatchStat[] = batches.map((b, i) => {
  const running = i < 2
  const tested = running ? Math.round(b.count * (i === 0 ? 0.62 : 0.35)) : b.count
  const failRate = b.defect_ratio * (b.batch_factor > 1 ? 2.2 : 0.7) + (i === 0 ? 0.006 : 0)
  const failed = Math.round(tested * failRate)
  const aborted = Math.round(tested * 0.006)
  const plan = b.model === 'HVP1307G17-1' ? plans[1] : i === 6 ? plans[3] : plans[0]
  const started = running ? now - (i === 0 ? 5.2 : 2.1) * HOUR : now - (i * 22 + 10) * HOUR
  return {
    batch_id: b.batch_id, model: b.model, count: b.count, tested,
    passed: tested - failed - aborted, failed, aborted,
    plan_id: plan.plan_id, plan_version: plan.version,
    machine_ids: b.model === 'HVP1307G17-1' ? ['M09', 'M10'] : running ? ['M01', 'M02', 'M03', 'M04', 'M06', 'M07', 'M11'] : ['M01', 'M02', 'M03', 'M04', 'M05', 'M06', 'M07', 'M08'],
    started_at: started,
    ended_at: running ? null : started + between(7, 10) * HOUR,
    state: running ? 'running' : i === 4 ? 'stopped' : 'done',
    rc_mean: +(RC_MEAN[b.model] * b.batch_factor + gauss(0, 0.03)).toFixed(3),
    rc_sd: +between(0.09, 0.16).toFixed(3),
    top_fail: i === 4 ? 'Temp_T1-T14' : pick(FAILS.slice(0, 3)),
  }
})

/* 已到料、尚未开测的批次（没有统计行） */
batches.push(
  { batch_id: `B-tb172-${hex()}`, model: 'tb172', count: 600, defect_ratio: 0.03, batch_factor: 1.0 },
  { batch_id: `B-HVP1307G17-1-${hex()}`, model: 'HVP1307G17-1', count: 240, defect_ratio: 0.03, batch_factor: 1.0 },
  { batch_id: `B-tb179-${hex()}`, model: 'tb179', count: 300, defect_ratio: 0.03, batch_factor: 1.0 },
)

/* ---------- 机台 ---------- */
const STATUS: [MachineStatus, CommStatus, string, string][] = [
  ['READY', 'ONLINE', '', ''], ['READY', 'ONLINE', '', ''], ['READY', 'ONLINE', '', ''], ['READY', 'ONLINE', '', ''],
  ['FAULT', 'ONLINE', '', 'PLC_FAULT · PLC 无响应'], ['READY', 'ONLINE', '', ''], ['READY', 'ONLINE', '', ''], ['MAINTENANCE', 'ONLINE', '', ''],
  ['READY', 'ONLINE', '', ''], ['READY', 'ONLINE', '', ''], ['READY', 'DEGRADED', '丢包', ''], ['READY', 'DISCONNECTED', '', ''],
]

export function makeMachines(): Machine[] {
  return STATUS.map(([status, comm, note, alarm], i) => {
    const n = i + 1
    const id = `M${String(n).padStart(2, '0')}`
    const hvp = n === 9 || n === 10
    const plan = hvp ? plans[1] : plans[0]
    const running = status === 'READY' && comm !== 'DISCONNECTED'
    const slots: Slot[] = Array.from({ length: 10 }, (_, k) => {
      let phase: Slot['phase'] = running ? pick(SLOT_PHASES) : 'IDLE'
      if (running && rand() < 0.35) phase = 'SAMPLING'
      if (n === 3 && k === 6) phase = 'ERROR'
      if (n === 5 && k < 2) phase = 'ERROR'
      const ta = 24 + n * 0.08 + gauss(0, 0.15)
      return {
        index: k + 1,
        phase,
        serial_number: phase === 'IDLE' || phase === 'RESETTING' || phase === 'PREHEATING' ? null : `${hvp ? batches[1].batch_id : batches[0].batch_id}-${String(Math.round(between(100, 380))).padStart(4, '0')}`,
        tests_done: Math.round(between(1800, 2600)),
        last_error: phase === 'ERROR' ? (n === 3 ? 'VACUUM_LEAK · 真空未到位（-44.8 kPa）' : 'PLC 无响应') : '',
        power_w: phase === 'SAMPLING' ? plan.power_w + gauss(0, 0.004) : 0,
        vacuum_kpa: ['WAITING_LOAD', 'CLAMPING', 'SAMPLING'].includes(phase) ? -85 + gauss(0, 0.6) : -2 + gauss(0, 0.3),
        t0: phase === 'SAMPLING' ? 43 + gauss(0, 0.4) : 45 + gauss(0, 0.05),
        t1: phase === 'SAMPLING' ? 41 + gauss(0, 0.4) : ta + 0.4,
        ta,
        progress: phase === 'SAMPLING' ? Math.round(between(5, 95)) : 0,
        run_id: phase === 'IDLE' ? null : `R-${id}-${k + 1}-${hex().slice(0, 10)}`,
      }
    })
    return {
      machine_id: id,
      serial: `X9610_${n}#`,
      fixture: `513000${String(n).padStart(2, '0')}`,
      holder: `V01_00${String(10 + n * 3).padStart(2, '0')}`,
      thermal_boards: `TM_BOX_V3_56F${n}001;TM_BOX_V3_56F${n}5001`,
      plc: n % 2 ? 'INOVANCE' : 'OMRON',
      firmware: n === 12 ? 'VC_BASE_BOX_V2' : 'VC_BASE_BOX_V3',
      slot_count: 10,
      status,
      comm_status: comm,
      comm_note: note,
      speed: 1,
      room_temp_c: +(23.6 + n * 0.11 + gauss(0, 0.1)).toFixed(2),
      alarm,
      plan_id: status === 'MAINTENANCE' ? null : plan.plan_id,
      plan_version: status === 'MAINTENANCE' ? null : plan.version,
      capability: CAPABILITY,
      slots,
    }
  })
}

/* ---------- 测试记录 + 5 分钟聚合 ---------- */
export function makeRuns(n = 260): Run[] {
  const list: Run[] = []
  for (let i = 0; i < n; i++) {
    const m = `M${String(1 + Math.floor(rand() * 11)).padStart(2, '0')}`
    const hvp = m === 'M09' || m === 'M10'
    const model = hvp ? 'HVP1307G17-1' : 'tb172'
    const off = m === 'M07' ? 0.09 : m === 'M03' ? -0.05 : 0
    const rc = RC_MEAN[model] + off + gauss(0, 0.11)
    const dt01 = (hvp ? 2.9 : 2.07) + off * 4 + gauss(0, 0.18)
    const r = rand()
    const status = r < 0.006 ? 'ABORTED' : r < 0.01 ? 'FAULT' : 'COMPLETED'
    const fail = status === 'COMPLETED' && (dt01 > (hvp ? 3.4 : 2.8) || rand() < 0.012)
    list.push({
      run_id: `R-${m}-${1 + Math.floor(rand() * 10)}-${hex()}${hex().slice(0, 2)}`,
      machine_id: m, slot_index: 1 + Math.floor(rand() * 10),
      serial_number: `${hvp ? batches[1].batch_id : batches[0].batch_id}-${String(i + 1).padStart(4, '0')}`,
      plan_id: hvp ? plans[1].plan_id : plans[0].plan_id, plan_version: hvp ? 3 : 2,
      status, passed: status === 'COMPLETED' ? !fail : null,
      fail_items: fail ? [dt01 > 2.8 ? 'Temp_T0-T1' : pick(FAILS)] : [],
      keep_result: status !== 'FAULT',
      rc: status === 'COMPLETED' ? +rc.toFixed(3) : null,
      dt01: status === 'COMPLETED' ? +dt01.toFixed(3) : null,
      ended_at: now - i * 40_000,
    })
  }
  return list
}

export function makeAgg(hours = 8): Agg5m[] {
  const n = (hours * 60) / 5
  const out: Agg5m[] = []
  const start = Math.floor((now - hours * HOUR) / (5 * MIN)) * 5 * MIN
  for (let i = 0; i < n; i++) {
    const lunch = i > 46 && i < 54
    const tests = lunch ? Math.round(between(8, 20)) : Math.round(between(52, 68))
    const failRate = i > 80 && i < 88 ? 0.07 : 0.022
    const failed = Math.round(tests * (failRate + gauss(0, 0.006)))
    const aborted = rand() < 0.15 ? 1 : 0
    out.push({
      bucket: start + i * 5 * MIN, tests, failed: Math.max(0, failed), aborted, passed: tests - Math.max(0, failed) - aborted,
      rc_mean: +(4.8 + (i > 80 && i < 88 ? 0.06 : 0) + gauss(0, 0.012)).toFixed(3),
      dt01_mean: +(2.1 + gauss(0, 0.03)).toFixed(3),
    })
  }
  return out
}

/* ---------- 告警 ---------- */
export const seedAlarms: Alarm[] = [
  { id: 'AL-10421', time: now - 3 * MIN, level: 'critical', machine_id: 'M05', source: '机台', code: 'PLC_FAULT', message: 'PLC 无响应，机台进入 FAULT，槽位 1、2 进入 ERROR', acked: false },
  { id: 'AL-10420', time: now - 7 * MIN, level: 'critical', machine_id: 'M12', source: '通信', code: 'COMM_DISCONNECT', message: '通信断开（DISCONNECTED），状态查询与指令下发均返回 503', acked: false },
  { id: 'AL-10419', time: now - 9 * MIN, level: 'major', machine_id: 'M03', slot_index: 7, source: '槽位', code: 'VACUUM_LEAK', message: '真空未到位：-44.8 kPa（吸附阈值 -60 kPa），槽位进入 ERROR', acked: false },
  { id: 'AL-10418', time: now - 15 * MIN, level: 'major', machine_id: 'M07', source: '漂移', code: 'EQUIPMENT_ANOMALY', message: 'T1 通道估计漂移 +0.18 ℃，超过 0.15 ℃ 设备异常阈值', acked: false },
  { id: 'AL-10417', time: now - 22 * MIN, level: 'minor', machine_id: 'M11', source: '通信', code: 'PACKET_LOSS', message: '通信降级（DEGRADED · 丢包），近 5 分钟采样缺行 3.2%', acked: true },
  { id: 'AL-10416', time: now - 31 * MIN, level: 'minor', machine_id: 'M02', slot_index: 4, source: '数据', code: 'SENSOR_99999', message: 'T9 读数 99999（接触不良哨兵值），本次判定为不合格', acked: true },
  { id: 'AL-10415', time: now - 48 * MIN, level: 'major', machine_id: 'M04', source: '判定', code: 'Temp_T0-T1', message: '连续 3 片 Temp_T0-T1 超上限 2.8 ℃', acked: true },
  { id: 'AL-10414', time: now - 70 * MIN, level: 'minor', machine_id: 'M06', source: '机台', code: 'AMBIENT_EXCURSION', message: '房间温度 27.3 ℃ 超出方案范围 23–27 ℃', acked: true },
  { id: 'AL-10413', time: now - 2.5 * HOUR, level: 'major', machine_id: 'M07', slot_index: 2, source: '槽位', code: 'ROBOT_PICK_FAIL', message: '机械手取放失败，槽位进入 ERROR，已 clear-error 恢复', acked: true },
  { id: 'AL-10412', time: now - 5 * HOUR, level: 'minor', machine_id: 'M07', source: '判定', code: 'Temp_T1-T14', message: 'Temp_T1-T14 偏高 0.4 ℃（未超限），趋势上升', acked: true },
]

/* ---------- 一致性：漂移、补偿、通道偏差估计 ---------- */
export const drifts: Record<string, Drift[]> = {
  M03: [{ drift_id: 'D-3a91', machine_id: 'M03', channel: 'T0', kind: 'FIXED', value: 0.3, step_at: 0, current: 0.3 }],
  M07: [
    { drift_id: 'D-7f02', machine_id: 'M07', channel: 'T1', kind: 'LINEAR', value: 0.0008, step_at: 0, current: 0.18 },
    { drift_id: 'D-7f03', machine_id: 'M07', channel: 'Ta', kind: 'HOURLY', value: 0.002, step_at: 0, current: 0.05 },
  ],
  M10: [{ drift_id: 'D-a1c4', machine_id: 'M10', channel: 'T5', kind: 'RANDOM_WALK', value: 0.01, step_at: 0, current: -0.07 }],
}
export const compensation: Record<string, { channel: string; value: number }[]> = {
  M01: [{ channel: 'T0', value: 0.5 }],
  M03: [{ channel: 'T0', value: -0.25 }],
}
/** 用 10 片 HVP1307G17-1 标准样品复测估计出的各通道偏差（℃）：本地后端计算 */
export function channelBias(mid: string) {
  const n = +mid.slice(1)
  return TEMP_CHANNELS.slice(0, 16).map((ch, i) => {
    let v = Math.sin(n * 3.1 + i * 1.7) * 0.03
    if (mid === 'M07' && ch === 'T1') v = 0.182
    if (mid === 'M07' && ch === 'Ta') v = 0.052
    if (mid === 'M03' && ch === 'T0') v = 0.048
    if (mid === 'M10' && ch === 'T5') v = -0.074
    return { channel: ch, value: +v.toFixed(3) }
  })
}
/** 各机台标准样品 Rc 相对全线中位数的偏差（℃/W） */
export const rcBias: Record<string, number> = {
  M01: 0.008, M02: -0.012, M03: -0.046, M04: 0.015, M05: 0.004, M06: -0.006, M07: 0.094, M08: 0.011, M09: -0.009, M10: 0.021, M11: 0.003, M12: -0.018,
}

export const faultCatalog: FaultInfo[] = [
  'SENSOR_99999:sensor:1', 'EARLY_STOP:sensor:1', 'PACKET_LOSS:communication:1', 'heater_dead:actuator:0', 'VACUUM_LEAK:actuator:1', 'CYLINDER_STUCK:actuator:1',
  'AMBIENT_EXCURSION:environment:1', 'COMM_DISCONNECT:communication:1', 'COMM_DELAY:communication:1', 'PLC_FAULT:plc:1', 'THERMAL_BOARD_DISCONNECT:sensor:1',
  'HEATER_POWER_LOSS:actuator:1', 'DUPLICATE_REPORT:communication:1', 'FIELD_MISALIGNMENT:communication:1', 'SENSOR_SPIKE:sensor:1', 'ROBOT_PICK_FAIL:actuator:1',
  'power_bias:actuator:0', 'force_axis_drift:actuator:0', 'contact_degraded:actuator:0', 'SENSOR_OPEN:sensor:1', 'SENSOR_9999:sensor:1', 'SENSOR_UNPARSEABLE:sensor:1',
  'SENSOR_STUCK:sensor:1', 'PRESS_TIMEOUT:actuator:1', 'HEATER_RUNAWAY:actuator:1', 'poor_contact:fixture:0',
].map((s) => { const [kind, layer, a] = s.split(':'); return { kind, layer: layer as FaultInfo['layer'], alarms: a === '1' } })

export const SCENARIOS = [
  { name: 'slow_drift', text: '通道线性慢漂移' },
  { name: 'sudden_bias', text: '通道固定偏置' },
  { name: 'vacuum_leak', text: '真空泄漏' },
  { name: 'packet_loss', text: '通信丢包' },
]

/** 每台机台用过的方案（本地 plan_dispatch 表） */
export function planHistory(mid: string) {
  const hvp = mid === 'M09' || mid === 'M10'
  return [
    { plan_id: hvp ? 'PLAN-3f2c71d0' : 'PLAN-592bbc46', name: hvp ? 'HVP 3.5W 标准测试' : '45度测3分钟', version: hvp ? 3 : 2, from: now - 5.2 * HOUR, to: null as number | null, runs: 412 },
    { plan_id: 'PLAN-a6109ec7', name: '现场观察', version: 4, from: now - 30 * HOUR, to: now - 29 * HOUR, runs: 18 },
    { plan_id: hvp ? 'PLAN-3f2c71d0' : 'PLAN-592bbc46', name: hvp ? 'HVP 3.5W 标准测试' : '45度测3分钟', version: hvp ? 2 : 1, from: now - 6 * 24 * HOUR, to: now - 30 * HOUR, runs: 3120 },
    { plan_id: 'PLAN-7c04be19', name: 'tb 系列 90° 竖放', version: 1, from: now - 9 * 24 * HOUR, to: now - 8 * 24 * HOUR, runs: 640 },
  ]
}

/* ---------- AI 模块与 Token ---------- */
export const AI_MODULES: { id: AiModule; name: string; where: string; desc: string; model: string; trigger: '用户' | '自动' | '用户 + 自动' }[] = [
  { id: 'agent.analysis', name: '跨批次分析', where: 'AI Agent', desc: '按型号 / 批次 / 机台 / 方案对比、归因、趋势预测', model: 'deepseek-v3', trigger: '用户' },
  { id: 'agent.plan', name: '方案生成', where: 'AI Agent · 测试方案', desc: '自然语言 → CreatePlanIn 结构化方案，附校验说明', model: 'qwen3-max', trigger: '用户' },
  { id: 'agent.ops', name: '设备操作', where: 'AI Agent', desc: '解析操作意图并生成待确认的集群 API 调用（上电 / 下发 / 补偿…）', model: 'qwen3-max', trigger: '用户' },
  { id: 'report', name: '报告生成', where: '测试执行 · 报告', desc: '批次报告总结、Agent 计算并绘制补充图表', model: 'deepseek-v3', trigger: '用户' },
  { id: 'anomaly', name: '异常归因', where: '运行总览 · 告警', desc: '新告警自动归因：区分设备异常 / 产品缺陷 / 数据异常', model: 'deepseek-v3', trigger: '自动' },
  { id: 'calib', name: '补偿建议', where: '设备配置 · 一致性', desc: '每日基于标准样品复测给出通道补偿建议', model: 'qwen3-max', trigger: '用户 + 自动' },
]
export const TOKEN_SHARE: Record<AiModule, [number, number, number]> = {
  // [日均调用, 平均输入 token, 平均输出 token]
  'agent.analysis': [46, 9200, 1400],
  'agent.plan': [18, 3800, 900],
  'agent.ops': [22, 2600, 380],
  report: [9, 21000, 3200],
  anomaly: [140, 1800, 260],
  calib: [12, 5200, 700],
}
export function tokenDaily(days = 30) {
  return Array.from({ length: days }, (_, d) => {
    const ts = now - (days - 1 - d) * 24 * HOUR
    const wk = new Date(ts).getDay()
    const f = wk === 0 || wk === 6 ? 0.35 : 1
    const row: Record<string, number> & { ts: number } = { ts } as any
    ;(Object.keys(TOKEN_SHARE) as AiModule[]).forEach((m) => {
      const [c, i, o] = TOKEN_SHARE[m]
      row[m] = Math.round(c * f * between(0.7, 1.3) * (i + o))
    })
    return row
  })
}
export function tokenCalls(n = 40) {
  const mods = Object.keys(TOKEN_SHARE) as AiModule[]
  return Array.from({ length: n }, (_, i) => {
    const m = pick(mods)
    const [, ii, oo] = TOKEN_SHARE[m]
    return {
      id: `call-${hex()}`,
      time: now - i * between(1, 6) * MIN,
      module: m,
      user: AI_MODULES.find((x) => x.id === m)!.trigger === '自动' ? '系统' : pick(['李明远', '王工', '周工']),
      input: Math.round(ii * between(0.5, 1.6)),
      output: Math.round(oo * between(0.5, 1.6)),
      latency: Math.round(between(800, 9000)),
      ok: rand() > 0.03,
    }
  })
}
