import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { Agg5m, Alarm, BatchStat, Machine, Run, Slot } from '@/api/types'
import { api, clearSession, wsUrl } from '@/api/http'

const TOPICS = ['fleet', 'slots', 'runs', 'alarms', 'agg_5m', 'batches', 'production']

function asList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[]
  if (data && typeof data === 'object' && Array.isArray((data as { items?: T[] }).items)) return (data as { items: T[] }).items
  return []
}

/**
 * 实时数据：先拉 REST 快照，再订 WebSocket。暂停只挡渲染。
 */
export const useLiveStore = defineStore('live', () => {
  const machines = ref<Machine[]>([])
  const alarms = ref<Alarm[]>([])
  const runs = ref<Run[]>([])
  const agg = ref<Agg5m[]>([])
  const batchStats = ref<BatchStat[]>([])
  const production = ref<{ batch_id: string; queue_remaining: number; plan_id: string; plan_version: number } | null>(null)
  const rcBias = ref<Record<string, number>>({})
  const planNames = ref<Record<string, string>>({})
  const pipeline = ref<Record<string, { v: string; state: 'ok' | 'warn' | 'danger' | 'idle' }>>({})
  const anomaly = ref<{ hours: number[]; series: Record<string, number[]> }>({ hours: [], series: {} })
  const paused = ref(false)
  const lastUpdate = ref(Date.now())
  const hydrated = ref(false)

  const link = computed<'online' | 'degraded' | 'offline'>(() => {
    if (!hydrated.value) return 'offline'
    const ms = machines.value
    if (!ms.length) return 'degraded'
    const bad = ms.filter((m) => m.comm_status !== 'ONLINE').length
    return bad === 0 ? 'online' : bad === ms.length ? 'offline' : 'degraded'
  })

  const kpi = computed(() => {
    const ms = machines.value
    const online = ms.filter((m) => m.comm_status !== 'DISCONNECTED' && !['OFFLINE', 'STOPPED'].includes(m.status)).length
    const slots = ms.flatMap((m) => (m.comm_status === 'DISCONNECTED' ? [] : m.slots || []))
    const busy = slots.filter((s) => !['IDLE', 'ERROR', 'COMPLETED'].includes(s.phase)).length
    const err = slots.filter((s) => s.phase === 'ERROR').length
    const shift = agg.value.slice(-96)
    const tests = shift.reduce((a, b) => a + b.tests, 0)
    const passed = shift.reduce((a, b) => a + b.passed, 0)
    const recent = runs.value.filter((r) => r.rc !== null).slice(0, 120)
    return {
      online,
      total: ms.length,
      busy,
      err,
      slotTotal: ms.reduce((a, m) => a + (m.slot_count || m.slots?.length || 0), 0),
      tests,
      yieldRate: (passed / Math.max(1, tests)) * 100,
      rc: recent.reduce((a, r) => a + r.rc!, 0) / Math.max(1, recent.length),
      openAlarms: alarms.value.filter((a) => !a.acked).length,
      critical: alarms.value.filter((a) => !a.acked && a.level === 'critical').length,
    }
  })

  function touch() {
    if (!paused.value) lastUpdate.value = Date.now()
  }

  function mergeMachine(partial: Partial<Machine> & { machine_id: string }) {
    const i = machines.value.findIndex((m) => m.machine_id === partial.machine_id)
    if (i < 0) {
      machines.value.push({
        machine_id: partial.machine_id,
        serial: partial.serial || '',
        fixture: partial.fixture || '',
        holder: partial.holder || '',
        thermal_boards: partial.thermal_boards || '',
        plc: partial.plc || 'INOVANCE',
        firmware: partial.firmware || '',
        slot_count: partial.slot_count || (partial.slots?.length ?? 0),
        status: partial.status || 'CREATED',
        comm_status: partial.comm_status || 'ONLINE',
        comm_note: partial.comm_note || '',
        speed: partial.speed ?? 1,
        room_temp_c: partial.room_temp_c ?? 0,
        alarm: partial.alarm || '',
        plan_id: partial.plan_id ?? null,
        plan_version: partial.plan_version ?? null,
        capability: partial.capability || {
          temp_channels: [], force_channels: [], duration_low_s: 0, duration_high_s: 0,
          power_low_w: 0, power_high_w: 0, force_low_g: 0, force_high_g: 0,
        },
        slots: partial.slots || [],
      })
      return
    }
    const prev = machines.value[i]
    machines.value[i] = {
      ...prev,
      ...partial,
      slots: partial.slots ?? prev.slots,
      capability: partial.capability ?? prev.capability,
    }
  }

  function upsertAlarm(row: Alarm) {
    const i = alarms.value.findIndex((a) => a.id === row.id)
    if (i < 0) alarms.value.unshift(row)
    else alarms.value[i] = { ...alarms.value[i], ...row }
  }

  function upsertBatch(row: BatchStat) {
    const i = batchStats.value.findIndex((b) => b.batch_id === row.batch_id)
    if (i < 0) batchStats.value.unshift(row)
    else batchStats.value[i] = { ...batchStats.value[i], ...row }
  }

  function applyMessage(msg: { topic?: string; data?: unknown }) {
    if (paused.value && msg.topic !== 'ping') return
    if (msg.topic === 'ping') return
    if (msg.topic === 'fleet') asList<Machine>(msg.data).forEach((m) => { if (m?.machine_id) mergeMachine(m) })
    else if (msg.topic === 'slots') {
      const body = msg.data as { machine_id?: string; slots?: Slot[] } | null
      if (body?.machine_id && Array.isArray(body.slots)) mergeMachine({ machine_id: body.machine_id, slots: body.slots })
    } else if (msg.topic === 'runs') {
      const row = (Array.isArray(msg.data) ? msg.data[0] : msg.data) as Run | undefined
      if (row?.run_id) {
        const i = runs.value.findIndex((r) => r.run_id === row.run_id)
        if (i < 0) runs.value.unshift(row)
        else runs.value[i] = row
        if (runs.value.length > 600) runs.value.pop()
      }
    } else if (msg.topic === 'alarms') {
      const row = (Array.isArray(msg.data) ? msg.data[0] : msg.data) as Alarm | undefined
      if (row?.id) upsertAlarm(row)
    } else if (msg.topic === 'agg_5m') {
      const row = (Array.isArray(msg.data) ? msg.data[0] : msg.data) as Agg5m | undefined
      if (row?.bucket != null) {
        const i = agg.value.findIndex((a) => a.bucket === row.bucket)
        if (i < 0) agg.value.push(row)
        else agg.value[i] = row
      }
    } else if (msg.topic === 'batches') {
      const row = (Array.isArray(msg.data) ? msg.data[0] : msg.data) as BatchStat | undefined
      if (row?.batch_id) upsertBatch(row)
    } else if (msg.topic === 'production') {
      const row = msg.data as { batch_id?: string; queue_remaining?: number; plan_id?: string; plan_version?: number } | null
      production.value = row?.batch_id ? {
        batch_id: row.batch_id,
        queue_remaining: row.queue_remaining ?? 0,
        plan_id: row.plan_id ?? '',
        plan_version: row.plan_version ?? 0,
      } : null
    }
    touch()
  }

  async function read<T>(path: string, timeoutMs = 12_000): Promise<T | null> {
    try {
      return await api<T>(path, { signal: AbortSignal.timeout(timeoutMs) })
    } catch {
      return null
    }
  }

  async function snapshot() {
    const [mr, ar, gr, pr, pipe] = await Promise.all([
      read<Machine[] | { items: Machine[] }>('/machines'),
      read<{ items: Alarm[] }>('/alarms?limit=50'),
      read<Agg5m[] | { items: Agg5m[] }>(`/stats/agg5m?from=${Date.now() - 8 * 3600_000}`),
      read<{ batch_id?: string; queue_remaining?: number; plan_id?: string; plan_version?: number } | null>('/production'),
      read<Record<string, { text?: string; state?: 'ok' | 'warn' | 'danger' | 'idle' }>>('/stats/pipeline'),
    ])
    const nextMachines = asList<Machine>(mr).map((m) => ({ ...m, slots: m.slots || [] }))
    if (nextMachines.length) machines.value = nextMachines
    if (ar) alarms.value = ar.items || []
    if (gr) agg.value = asList<Agg5m>(gr)
    production.value = pr?.batch_id ? {
      batch_id: pr.batch_id,
      queue_remaining: pr.queue_remaining ?? 0,
      plan_id: pr.plan_id ?? '',
      plan_version: pr.plan_version ?? 0,
    } : null
    if (pipe) {
      pipeline.value = Object.fromEntries(
        Object.entries(pipe).map(([key, step]) => [key, { v: step.text || '', state: step.state || 'idle' }]),
      )
    }
    hydrated.value = true
    touch()

    const [rr, br, bias, pl, trend] = await Promise.all([
      read<{ items: Run[] }>('/runs?limit=80', 8_000),
      read<BatchStat[] | { items: BatchStat[] }>('/batch-stats?limit=50'),
      read<{ items: { machine_id: string; bias: number }[] }>('/stats/rc-bias'),
      read<{ plan?: { plan_id?: string; name?: string } }[]>('/plans'),
      read<{ hours?: number[]; series?: Record<string, number[]> }>('/stats/anomaly-trend?hours=8'),
    ])
    if (rr) runs.value = rr.items || []
    if (br) batchStats.value = asList<BatchStat>(br)
    if (bias) rcBias.value = Object.fromEntries((bias.items || []).map((row) => [row.machine_id, row.bias]))
    if (pl) {
      planNames.value = Object.fromEntries(
        pl.filter((row) => row.plan?.plan_id && row.plan?.name).map((row) => [row.plan!.plan_id!, row.plan!.name!]),
      )
    }
    if (trend) anomaly.value = { hours: trend.hours || [], series: trend.series || {} }
    touch()
  }

  let socket: WebSocket | null = null
  let reconnect: ReturnType<typeof setTimeout> | null = null

  async function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return
    let url = ''
    try {
      url = await wsUrl()
    } catch {
      return
    }
    const ws = new WebSocket(url)
    socket = ws
    ws.onopen = () => {
      ws.send(JSON.stringify({ op: 'subscribe', topics: TOPICS }))
    }
    ws.onmessage = (ev) => {
      try { applyMessage(JSON.parse(ev.data)) } catch { /* 忽略非 JSON */ }
    }
    ws.onclose = (ev) => {
      if (socket === ws) socket = null
      if (ev.code === 4401) {
        clearSession()
        if (!location.hash.startsWith('#/login')) location.hash = '#/login'
        return
      }
      if (reconnect) clearTimeout(reconnect)
      reconnect = setTimeout(() => { void snapshot(); void connect() }, 3000)
    }
  }

  async function ack(id: string) {
    const row = alarms.value.find((item) => item.id === id)
    if (row) row.acked = true
    try {
      await api(`/alarms/${encodeURIComponent(id)}/ack`, {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
      })
    } catch {
      if (row) row.acked = false
    }
  }

  async function ackAll() {
    const previous = alarms.value.map((item) => item.acked)
    alarms.value.forEach((item) => { item.acked = true })
    try {
      await api('/alarms/ack-all', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
      })
    } catch {
      alarms.value.forEach((item, index) => { item.acked = previous[index] })
    }
  }

  function machine(id: string) {
    return machines.value.find((item) => item.machine_id === id)
  }

  let started = false
  function start() {
    if (started) return
    started = true
    void snapshot().then(() => connect())
  }

  return { machines, alarms, runs, agg, batchStats, production, rcBias, planNames, pipeline, anomaly, paused, lastUpdate, link, kpi, start, ack, ackAll, machine }
})
