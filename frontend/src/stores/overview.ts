import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, wsUrl } from '@/api/http'
import type { Agg5m, Alarm, Machine, Slot } from '@/api/types'

export interface MachineView extends Machine {
  last_sync_at: number
  yield_recent: { n: number; passed: number }
}

interface KpiRaw {
  online: number
  total: number
  busy_slots: number
  error_slots: number
  slot_total: number
  tests: number
  yield_rate: number
  rc_mean: number
  open_alarms: number
  critical_alarms: number
  prev: { tests: number; yield_rate: number }
}

interface PipelineStep { text: string; state: 'ok' | 'warn' | 'danger' | 'idle' }
interface PipelineRaw {
  gen: PipelineStep
  check: PipelineStep
  dispatch: PipelineStep
  collect: PipelineStep
  anomaly: PipelineStep
  calib: PipelineStep
  report: PipelineStep
}

const emptyKpi: KpiRaw = {
  online: 0, total: 0, busy_slots: 0, error_slots: 0, slot_total: 0,
  tests: 0, yield_rate: 0, rc_mean: 0, open_alarms: 0, critical_alarms: 0,
  prev: { tests: 0, yield_rate: 0 },
}

export const useOverviewStore = defineStore('overview', () => {
  const machines = ref<MachineView[]>([])
  const alarms = ref<Alarm[]>([])
  const agg = ref<Agg5m[]>([])
  const anomaly = ref<{ hours: number[]; series: Record<string, number[]> }>({ hours: [], series: {} })
  const rc = ref<{ median: number; items: { machine_id: string; bias: number }[] }>({ median: 0, items: [] })
  const pipeline = ref<PipelineRaw | null>(null)
  const kpiRaw = ref<KpiRaw>(emptyKpi)
  const paused = ref(false)
  const range = ref<'2h' | '8h'>('8h')
  const error = ref('')
  const ready = ref(false)

  const kpi = computed(() => ({
    online: kpiRaw.value.online,
    total: kpiRaw.value.total,
    busy: kpiRaw.value.busy_slots,
    err: kpiRaw.value.error_slots,
    slotTotal: kpiRaw.value.slot_total,
    tests: kpiRaw.value.tests,
    yieldRate: kpiRaw.value.yield_rate,
    rc: kpiRaw.value.rc_mean,
    openAlarms: kpiRaw.value.open_alarms,
    critical: kpiRaw.value.critical_alarms,
    prevTests: kpiRaw.value.prev.tests,
    prevYield: kpiRaw.value.prev.yield_rate,
  }))

  const pipe = computed(() => {
    const step = (key: keyof PipelineRaw) => {
      const row = pipeline.value?.[key]
      return { v: row?.text ?? '—', state: row?.state ?? ('idle' as const) }
    }
    return {
      gen: step('gen'), check: step('check'), dispatch: step('dispatch'), collect: step('collect'),
      anomaly: step('anomaly'), calib: step('calib'), report: step('report'),
    }
  })

  let timer = 0
  let socket: WebSocket | null = null

  async function refresh() {
    const kpiRange = range.value === '2h' ? '2h' : 'shift'
    const from = range.value === '2h' ? Date.now() - 2 * 3_600_000 : ''
    const [machineRows, kpiBody, aggRows, trend, bias, pipeBody, alarmPage] = await Promise.all([
      api<MachineView[]>('/machines'),
      api<KpiRaw>(`/stats/kpi?range=${kpiRange}`),
      api<Agg5m[]>(`/stats/agg5m${from ? `?from=${from}` : ''}`),
      api<{ hours: number[]; series: Record<string, number[]> }>('/stats/anomaly-trend?hours=8'),
      api<{ median: number; items: { machine_id: string; bias: number }[] }>('/stats/rc-bias'),
      api<PipelineRaw>('/stats/pipeline'),
      api<{ items: Alarm[] }>('/alarms?limit=50'),
    ])
    machines.value = machineRows
    kpiRaw.value = kpiBody
    agg.value = aggRows
    anomaly.value = trend
    rc.value = bias
    pipeline.value = pipeBody
    alarms.value = alarmPage.items
    ready.value = true
    error.value = ''
  }

  function applyFleet(rows: MachineView[]) {
    for (const row of rows) {
      const index = machines.value.findIndex((item) => item.machine_id === row.machine_id)
      if (index < 0) continue
      const prev = machines.value[index]
      machines.value[index] = { ...prev, ...row, slots: prev.slots, capability: prev.capability, yield_recent: row.yield_recent ?? prev.yield_recent }
    }
  }

  function applySlots(payload: { machine_id: string; slots: Slot[] }) {
    const machine = machines.value.find((item) => item.machine_id === payload.machine_id)
    if (machine) machine.slots = payload.slots
  }

  function applyAlarm(alarm: Alarm) {
    const index = alarms.value.findIndex((item) => item.id === alarm.id)
    if (index < 0) alarms.value.unshift(alarm)
    else alarms.value[index] = alarm
  }

  function applyAgg(row: Agg5m) {
    const index = agg.value.findIndex((item) => item.bucket === row.bucket)
    if (index < 0) agg.value.push(row)
    else agg.value[index] = row
  }

  async function connect() {
    socket?.close()
    const url = await wsUrl()
    const ws = new WebSocket(url)
    socket = ws
    ws.onopen = () => ws.send(JSON.stringify({ op: 'subscribe', topics: ['fleet', 'slots', 'alarms', 'agg_5m'] }))
    ws.onmessage = (event) => {
      if (paused.value) return
      const msg = JSON.parse(event.data)
      if (msg.topic === 'fleet') applyFleet(msg.data)
      if (msg.topic === 'slots') applySlots(msg.data)
      if (msg.topic === 'alarms') applyAlarm(msg.data)
      if (msg.topic === 'agg_5m') applyAgg(msg.data)
    }
  }

  async function start() {
    if (timer) return
    try {
      await refresh()
      await connect()
    } catch (exc) {
      error.value = exc instanceof Error ? exc.message : '后端不可用'
    }
    timer = window.setInterval(async () => {
      if (paused.value) return
      try {
        await refresh()
      } catch (exc) {
        error.value = exc instanceof Error ? exc.message : '后端不可用'
      }
    }, 5000)
  }

  async function ack(id: string) {
    const body = await api<{ alarm: Alarm }>(`/alarms/${id}/ack`, {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
    applyAlarm(body.alarm)
    kpiRaw.value = { ...kpiRaw.value, open_alarms: alarms.value.filter((item) => !item.acked).length }
  }

  async function unack(id: string) {
    const body = await api<{ alarm: Alarm }>(`/alarms/${id}/unack`, {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
    applyAlarm(body.alarm)
    kpiRaw.value = { ...kpiRaw.value, open_alarms: alarms.value.filter((item) => !item.acked).length }
  }

  function machine(id: string) {
    return machines.value.find((item) => item.machine_id === id)
  }

  return {
    machines, alarms, agg, anomaly, rc, pipe, kpi, paused, range, error, ready,
    start, refresh, ack, unack, machine,
  }
})
