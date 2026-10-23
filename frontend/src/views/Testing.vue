<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowRight, Boxes, ChevronDown, CircleAlert, Code, Download, FileStack, FileText, Filter, ListChecks, Play, Search, Send, Square, X,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Panel from '@/components/Panel.vue'
import StatusTag from '@/components/StatusTag.vue'
import EChart from '@/components/EChart.vue'
import { api, apiBlob, wsUrl } from '@/api/http'
import { useAppStore } from '@/stores/app'
import { useSettingsStore } from '@/stores/settings'
import { useTokens } from '@/composables/useTokens'
import { ago, dt, hms } from '@/utils/format'
import type { Batch, BatchStat, Capability, Machine, Plan, PlanMeta, ProductModel, Run } from '@/api/types'

interface PlanItem { plan: Plan; meta: PlanMeta }
interface BatchRow extends Batch { remaining: number }
interface BatchStatRow extends BatchStat { eta_s: number | null }
interface RunRow extends Run { batch_id?: string }
interface Issue { level: 'ok' | 'warn' | 'danger'; text: string }
interface Page<T> { items: T[]; next_cursor: string | null }
interface StartOut { batch_id: string; accepted: string[]; skipped: { machine_id: string; reason: string }[]; audit_id: string }

const app = useAppStore()
const settings = useSettingsStore()
const tk = useTokens()
const route = useRoute()
const router = useRouter()

const tab = ref<'running' | 'history' | 'runs'>((route.query.tab as 'running' | 'history' | 'runs') || 'running')
watch(tab, (t) => router.replace({ query: { ...route.query, tab: t } }))

const loadError = ref('')
const plans = ref<Plan[]>([])
const versionsOf = ref<Record<string, number[]>>({})
const productModels = ref<ProductModel[]>([])
const batches = ref<BatchRow[]>([])
const batchStats = ref<BatchStatRow[]>([])
const machines = ref<Machine[]>([])
const runs = ref<RunRow[]>([])
const checks = ref<Issue[]>([])
const open = ref(!!route.query.plan)
const starting = ref(false)
const stopping = ref('')
const showBody = ref(false)
const form = ref({
  plan_id: (route.query.plan as string) || '',
  plan_version: 0,
  source: 'batch' as 'batch' | 'serials',
  batch_id: '',
  serials: '',
  machine_ids: [] as string[],
  auto_recover: true,
  max_count: null as number | null,
})

const published = computed(() => plans.value.filter((p) => p.version > 0))
const plan = computed(() => plans.value.find((p) => p.plan_id === form.value.plan_id && p.version === form.value.plan_version) ?? plans.value.find((p) => p.plan_id === form.value.plan_id))
const versions = computed(() => versionsOf.value[form.value.plan_id] ?? (plan.value ? [plan.value.version] : []))
const batch = computed(() => batches.value.find((b) => b.batch_id === form.value.batch_id))
const newCount = computed(() => batch.value?.remaining ?? 0)
const model = computed(() => productModels.value.find((m) => m.model === batch.value?.model))

function remaining(id: string) {
  return batches.value.find((b) => b.batch_id === id)?.remaining ?? 0
}
function machineOf(id: string): Machine {
  return machines.value.find((m) => m.machine_id === id) ?? {
    machine_id: id, serial: '', fixture: '', holder: '', thermal_boards: '', plc: 'INOVANCE', firmware: '',
    slot_count: 0, status: 'OFFLINE', comm_status: 'DISCONNECTED', comm_note: '', speed: 1, room_temp_c: 0,
    alarm: '', plan_id: null, plan_version: null,
    capability: { temp_channels: [], force_channels: [], duration_low_s: 0, duration_high_s: 0, power_low_w: 0, power_high_w: 0, force_low_g: 0, force_high_g: 0 } satisfies Capability,
    slots: [],
  }
}
function blockReason(m: Machine) {
  if (m.comm_status === 'DISCONNECTED') return '通信断开，不能下发'
  if (m.status === 'MAINTENANCE') return '维修中，需先结束维修'
  if (m.status === 'FAULT') return `故障：${m.alarm || '需先复位'}`
  return ''
}
function warnReason(m: Machine) {
  const busy = m.slots.some((s) => s.phase === 'SAMPLING')
  if (busy && m.plan_id !== form.value.plan_id) return '正在测量且方案不同，集群会跳过该机台'
  if (['OFFLINE', 'STOPPED'].includes(m.status)) return '关机状态，开始时会自动上电'
  return ''
}
function toggleMachine(id: string) {
  const s = form.value.machine_ids
  form.value.machine_ids = s.includes(id) ? s.filter((x) => x !== id) : [...s, id]
}
function selectAvailable() {
  form.value.machine_ids = machines.value.filter((m) => !blockReason(m)).map((m) => m.machine_id)
}
function pickBatch() {
  const power = plan.value?.power_w
  const fits = (row: BatchRow) => {
    const item = productModels.value.find((m) => m.model === row.model)
    return row.remaining > 0 && (power == null || item?.power_w === power)
  }
  if (form.value.batch_id && fits(batches.value.find((b) => b.batch_id === form.value.batch_id) ?? { remaining: 0 } as BatchRow)) return
  form.value.batch_id = (batches.value.find(fits) ?? batches.value[0])?.batch_id ?? ''
}

const body = computed(() => {
  const serials = form.value.serials.split(/[\s,，]+/).filter(Boolean)
  const payload: Record<string, unknown> = {
    machine_ids: form.value.machine_ids,
    plan_id: form.value.plan_id,
    plan_version: form.value.plan_version,
    auto_recover: form.value.auto_recover,
    max_count: form.value.max_count || null,
  }
  if (form.value.source === 'batch') payload.batch_id = form.value.batch_id
  else payload.serial_numbers = serials
  return payload
})
const blocked = computed(() => !form.value.plan_id || checks.value.some((c) => c.level === 'danger') || starting.value)

watch(() => form.value.plan_id, (id) => {
  if (!id) return
  const known = versions.value
  if (!known.includes(form.value.plan_version)) form.value.plan_version = known[known.length - 1] ?? 0
  pickBatch()
})
watch(() => form.value.plan_version, () => { loadPlanVersion().catch(() => undefined) })

async function loadPlanVersion() {
  const id = form.value.plan_id
  const version = form.value.plan_version
  if (!id || !version) return
  if (plans.value.some((p) => p.plan_id === id && p.version === version)) return
  const item = await api<PlanItem>(`/plans/${encodeURIComponent(id)}?version=${version}`)
  const index = plans.value.findIndex((p) => p.plan_id === id)
  if (index >= 0) plans.value[index] = item.plan
  else plans.value.push(item.plan)
}

let precheckTimer = 0
watch(body, () => {
  window.clearTimeout(precheckTimer)
  precheckTimer = window.setTimeout(runPrecheck, 400)
}, { deep: true })

async function runPrecheck() {
  if (!open.value || !form.value.plan_id) return
  try {
    const result = await api<{ ok: boolean; issues: { level: Issue['level']; message: string }[] }>('/production/precheck', {
      method: 'POST',
      body: JSON.stringify(body.value),
    })
    checks.value = result.issues.map((item) => ({ level: item.level, text: item.message }))
  } catch (exc) {
    checks.value = [{ level: 'danger', text: exc instanceof Error ? exc.message : '校验失败' }]
  }
}

async function submit() {
  if (!plan.value || blocked.value) return
  const ok = await app.confirm({
    title: '开始连续生产',
    desc: `「${plan.value.name}」v${form.value.plan_version} 将下发到 ${form.value.machine_ids.length} 台机台，从 ${form.value.source === 'batch' ? form.value.batch_id : '指定序列号'} 取片。`,
    confirmText: '确认下发',
    typeToConfirm: 'START',
    checklist: ['已核对型号与方案功率、压紧力匹配', '机台夹具与吸盘座状态正常', '知悉：方案不一致且正在测量的机台会被跳过'],
  })
  if (!ok) return
  starting.value = true
  try {
    const result = await api<StartOut>('/production/start', {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(body.value),
    })
    open.value = false
    tab.value = 'running'
    const skipped = result.skipped.length ? `，跳过 ${result.skipped.map((item) => item.machine_id).join('、')}` : ''
    app.toast({ kind: 'ok', title: '连续生产已开始', desc: `${result.batch_id} · 接受 ${result.accepted.length} 台${skipped}` })
    await refreshLive()
  } catch (exc) {
    app.toast({ kind: 'danger', title: '下发失败', desc: exc instanceof Error ? exc.message : '下发失败' })
  } finally {
    starting.value = false
  }
}

const runningBatches = computed(() => batchStats.value.filter((b) => b.state === 'running'))
const yieldOf = (b: BatchStat) => (b.tested ? (b.passed / b.tested) * 100 : 0)
function etaText(b: BatchStatRow) {
  if (b.eta_s == null) return '—'
  const min = Math.max(1, Math.round(b.eta_s / 60))
  return min > 60 ? `${Math.floor(min / 60)} 小时 ${min % 60} 分` : `${min} 分钟`
}
async function stop(b: BatchStat) {
  const ok = await app.confirm({ title: `停止 ${b.batch_id}`, desc: '在取下一片之前生效：正在测的均热板会测完，空闲槽位不再取新片。', danger: true, confirmText: '停止连续生产' })
  if (!ok) return
  stopping.value = b.batch_id
  try {
    await api('/production/stop', {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ batch_id: b.batch_id }),
    })
    app.toast({ kind: 'warn', title: '已停止连续生产', desc: b.batch_id })
    await refreshLive()
  } catch (exc) {
    app.toast({ kind: 'danger', title: '停止失败', desc: exc instanceof Error ? exc.message : '停止失败' })
  } finally {
    stopping.value = ''
  }
}
const stream = computed(() => runs.value.slice(0, 14))

const kw = ref('')
const modelFilter = ref('all')
const selected = ref<string[]>([])
const history = computed(() =>
  batchStats.value.filter((b) => (modelFilter.value === 'all' || b.model === modelFilter.value) && (b.batch_id + b.model).toLowerCase().includes(kw.value.toLowerCase())),
)
const allChecked = computed(() => history.value.length > 0 && history.value.every((b) => selected.value.includes(b.batch_id)))
function toggleAll() {
  selected.value = allChecked.value ? [] : history.value.map((b) => b.batch_id)
}
function toggle(id: string) {
  selected.value = selected.value.includes(id) ? selected.value.filter((x) => x !== id) : [...selected.value, id]
}
const planLabel = (id: string, v: number) => `${plans.value.find((p) => p.plan_id === id)?.name ?? id} · v${v}`
function report(ids: string[]) {
  router.push({ path: '/report', query: { b: ids.join(',') } })
}

const rf = ref({ machine: 'all', passed: 'all', kw: '' })
const passedQuery = computed(() => ({ all: '', pass: 'true', fail: 'false', none: 'null' }[rf.value.passed]))
const runList = computed(() => runs.value)
const reportBatches = computed(() => [...new Set(runs.value.map((r) => r.batch_id).filter((id): id is string => !!id))])
const runTag = (r: { status: string; passed: boolean | null }) => (r.status !== 'COMPLETED' ? r.status : r.passed ? 'PASS' : 'NG')

interface SamplePoint { t_s: number; T0: number; T1: number; Ta: number; power_w?: number }
interface GroundTruth {
  run_id: string
  model?: string
  grade?: string
  quality?: number
  contact_quality?: number
  defects?: { kind: string; severity: number }[]
  scenario_id?: string
  fault_kinds?: string[]
}
interface DeltaEntry { channel?: string; item?: string; name?: string; value?: unknown }

const selectedId = ref<string | null>(null)
const detail = ref<(RunRow & { result?: Record<string, unknown> }) | null>(null)
const detailError = ref('')
const samplesHint = ref('点开一条记录后拉取过程曲线')
const samplePoints = ref<SamplePoint[]>([])
const gt = ref<GroundTruth | null>(null)
const gtHint = ref('')
const detailVerdict = computed(() => {
  const row = detail.value
  if (!row) return 'fail'
  if (row.passed === true) return 'pass'
  if (row.passed === false) return 'fail'
  if ((row.fail_items || []).length) return 'fail'
  return row.status === 'COMPLETED' ? 'pass' : 'fail'
})
const failItemSet = computed(() => new Set((detail.value?.fail_items || []).map((item) => item.toLowerCase())))
function isFailDelta(key: string) {
  const name = key.toLowerCase()
  if (failItemSet.value.has(name) || failItemSet.value.has(`temp_${name}`)) return true
  return [...failItemSet.value].some((item) => item === name || name.endsWith(item) || item.endsWith(name))
}
const failItems = computed(() => detail.value?.fail_items || [])
const deltaRows = computed(() => {
  const result = detail.value?.result
  const raw = result?.deltas ?? (result && !('temps' in result) && !('seq' in result) ? result : null)
  if (!raw) return [] as { key: string; value: string; fail: boolean }[]
  const entries: [string, unknown][] = Array.isArray(raw)
    ? (raw as DeltaEntry[]).filter((row) => row && typeof row === 'object').map((row) => [String(row.channel || row.item || row.name || ''), row.value])
    : Object.entries(raw as Record<string, unknown>)
  return entries.filter(([key]) => key && key !== 'deltas').map(([key, value]) => ({
    key,
    value: typeof value === 'number' ? String(value) : JSON.stringify(value),
    fail: isFailDelta(key),
  }))
})
const curveOpt = computed(() => {
  const t = tk.value
  const points = samplePoints.value
  if (!points.length) return {}
  return {
    grid: { left: 40, right: 12, top: 28, bottom: 24 },
    legend: { data: ['T0 加热块', 'T1 板面', 'Ta 房间'] },
    xAxis: { type: 'category', data: points.map((point) => `${point.t_s.toFixed(1)}s`), boundaryGap: false, axisLabel: { interval: Math.ceil(points.length / 6) } },
    yAxis: { type: 'value', name: '℃', scale: true },
    series: [
      { name: 'T0 加热块', type: 'line', data: points.map((point) => point.T0), showSymbol: false, lineStyle: { width: 2, color: t.danger }, itemStyle: { color: t.danger } },
      { name: 'T1 板面', type: 'line', data: points.map((point) => point.T1), showSymbol: false, lineStyle: { width: 2, color: t.chart[0] }, itemStyle: { color: t.chart[0] } },
      { name: 'Ta 房间', type: 'line', data: points.map((point) => point.Ta), showSymbol: false, lineStyle: { width: 1, type: 'dashed', color: t['text-3'] }, itemStyle: { color: t['text-3'] } },
    ],
  }
})

async function openRun(runId: string) {
  selectedId.value = runId
  detail.value = null
  detailError.value = ''
  samplePoints.value = []
  gt.value = null
  gtHint.value = ''
  samplesHint.value = '正在拉取判定结果…'
  try {
    detail.value = await api<RunRow & { result?: Record<string, unknown> }>(`/runs/${encodeURIComponent(runId)}`)
  } catch (err) {
    detailError.value = err instanceof Error ? err.message : '详情没有读到'
    samplesHint.value = '详情失败，未拉曲线'
    return
  }
  samplesHint.value = '正在拉取过程曲线…'
  gtHint.value = '正在拉取仿真真值…'
  void loadSamples(runId)
  void loadGroundTruth(runId)
}

async function loadSamples(runId: string) {
  try {
    const body = await api<{ points?: SamplePoint[] }>(`/runs/${encodeURIComponent(runId)}/samples`)
    if (selectedId.value !== runId) return
    samplePoints.value = body.points || []
    samplesHint.value = samplePoints.value.length ? '' : '这条测试没有采样点'
  } catch (err) {
    if (selectedId.value !== runId) return
    samplesHint.value = err instanceof Error ? err.message : '曲线没有读到'
  }
}

async function loadGroundTruth(runId: string) {
  try {
    await settings.load()
  } catch { /* 开关以已经读到的系统设置为准 */ }
  if (selectedId.value !== runId) return
  if (settings.saved.source !== 'sim' || !settings.saved.sim.use_ground_truth) {
    gtHint.value = '未打开仿真真值开关（系统设置 · 仿真平台）'
    return
  }
  try {
    gt.value = await api<GroundTruth>(`/runs/${encodeURIComponent(runId)}/ground-truth`)
    if (selectedId.value === runId) gtHint.value = ''
  } catch (err) {
    if (selectedId.value !== runId) return
    gtHint.value = err instanceof Error ? err.message : '真值没有读到'
  }
}

async function pageAll<T>(path: string): Promise<T[]> {
  const items: T[] = []
  let cursor = ''
  for (let i = 0; i < 8; i += 1) {
    const page = await api<Page<T>>(`${path}${path.includes('?') ? '&' : '?'}limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`)
    items.push(...page.items)
    if (!page.next_cursor) break
    cursor = page.next_cursor
  }
  return items
}

async function refreshLive() {
  const query = new URLSearchParams()
  if (rf.value.machine !== 'all') query.set('machine_id', rf.value.machine)
  if (passedQuery.value) query.set('passed', passedQuery.value)
  if (rf.value.kw.trim()) query.set('q', rf.value.kw.trim())
  const [machineRows, statRows, batchRows, runRows] = await Promise.all([
    api<Machine[]>('/machines'),
    pageAll<BatchStatRow>('/batch-stats'),
    api<BatchRow[]>('/batches'),
    api<Page<RunRow>>(`/runs?limit=80&${query.toString()}`),
  ])
  machines.value = machineRows
  batchStats.value = statRows
  batches.value = batchRows
  runs.value = runRows.items
  loadError.value = ''
}

async function load() {
  const items = await api<PlanItem[]>('/plans')
  const modelRows = await api<ProductModel[]>('/models')
  plans.value = items.filter((item) => !item.meta.draft).map((item) => item.plan)
  versionsOf.value = Object.fromEntries(items.map((item) => [item.plan.plan_id, item.meta.versions.length ? item.meta.versions : [item.plan.version]]))
  productModels.value = modelRows
  await refreshLive()
  if (!form.value.plan_id) form.value.plan_id = published.value[0]?.plan_id ?? ''
  const known = versions.value
  if (!known.includes(form.value.plan_version)) form.value.plan_version = known[known.length - 1] ?? 0
  pickBatch()
  await runPrecheck()
}

let timer = 0
let socket: WebSocket | null = null
let runTimer = 0
watch(rf, () => {
  window.clearTimeout(runTimer)
  runTimer = window.setTimeout(() => { refreshLive().catch(() => undefined) }, 300)
}, { deep: true })

async function exportCsv() {
  try {
    const blob = await apiBlob('/export/production.csv')
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'production.csv'
    link.click()
    URL.revokeObjectURL(url)
    app.toast({ kind: 'ok', title: '已导出生产结果表' })
  } catch (exc) {
    app.toast({ kind: 'danger', title: '导出失败', desc: exc instanceof Error ? exc.message : '导出失败' })
  }
}

onMounted(async () => {
  try {
    await load()
    const opened = route.query.r
    if (typeof opened === 'string' && opened) await openRun(opened)
  } catch (exc) {
    loadError.value = exc instanceof Error ? exc.message : '后端不可用'
  }
  timer = window.setInterval(() => { refreshLive().catch((exc) => { loadError.value = exc instanceof Error ? exc.message : '后端不可用' }) }, 5000)
  try {
    const ws = new WebSocket(await wsUrl())
    socket = ws
    ws.onopen = () => ws.send(JSON.stringify({ op: 'subscribe', topics: ['production', 'runs', 'batches', 'slots'] }))
    ws.onmessage = (event) => {
      try {
        if (JSON.parse(event.data).topic === 'ping') return
      } catch { /* 刷新 */ }
      refreshLive().catch(() => undefined)
    }
  } catch {
    /* 轮询仍会刷新 */
  }
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  window.clearTimeout(precheckTimer)
  socket?.close()
})
</script>

<template>
  <div class="page">
    <p v-if="loadError" class="fs-sm" style="color: var(--c-danger); margin: 0">{{ loadError }}</p>
    <PageHeader title="测试执行" desc="下发方案并开始连续生产 · 跟踪批次进度 · 历史批次与报告">
      <button class="btn" @click="exportCsv"><Download :size="16" />导出结果表</button>
      <button class="btn btn-primary" @click="open = true"><Play :size="16" />新建测试任务</button>
    </PageHeader>

    <div class="tabs" role="tablist">
      <button role="tab" :aria-selected="tab === 'running'" @click="tab = 'running'">执行中 <span class="tag info">{{ runningBatches.length }}</span></button>
      <button role="tab" :aria-selected="tab === 'history'" @click="tab = 'history'">历史批次 <span class="tag">{{ batchStats.length }}</span></button>
      <button role="tab" :aria-selected="tab === 'runs'" @click="tab = 'runs'">测试记录</button>
    </div>

    <!-- 执行中 -->
    <template v-if="tab === 'running'">
      <div v-if="!runningBatches.length" class="empty">
        <Boxes :size="28" />
        <b>当前没有进行中的连续生产</b>
        <button class="btn btn-primary" @click="open = true"><Play :size="16" />新建测试任务</button>
      </div>
      <Panel v-for="b in runningBatches" :key="b.batch_id" accent="primary" flush>
        <div class="bh">
          <div class="col gap-4 grow" style="min-width: 0">
            <div class="row">
              <b class="mono" style="font-size: var(--fs-lg)">{{ b.batch_id }}</b>
              <StatusTag status="RUNNING" text="连续生产中" />
              <span class="tag">{{ b.model }}</span>
            </div>
            <span class="fs-sm muted">{{ planLabel(b.plan_id, b.plan_version) }} · 开始于 {{ ago(b.started_at) }} · 预计剩余 {{ etaText(b) }}</span>
          </div>
          <button class="btn" :disabled="!b.tested" @click="report([b.batch_id])"><FileText :size="16" />实时报告</button>
          <button class="btn btn-danger" :disabled="stopping === b.batch_id" @click="stop(b)"><Square :size="14" />{{ stopping === b.batch_id ? '停止中' : '停止' }}</button>
        </div>
        <div class="prog">
          <div class="row-between fs-sm">
            <span><b class="num" style="font-size: var(--fs-xl)">{{ b.tested }}</b><span class="muted num"> / {{ b.count }} 片</span></span>
            <span class="row gap-12 num">
              <span class="t-ok">通过 {{ b.passed }}</span><span class="t-danger">不合格 {{ b.failed }}</span><span class="t-warn">中止 {{ b.aborted }}</span>
              <span>良率 <b>{{ yieldOf(b).toFixed(2) }}%</b></span>
            </span>
          </div>
          <div class="stack" :aria-label="`进度 ${Math.round((b.tested / b.count) * 100)}%`">
            <i class="p" :style="{ width: `${(b.passed / b.count) * 100}%` }" />
            <i class="f" :style="{ width: `${(b.failed / b.count) * 100}%` }" />
            <i class="a" :style="{ width: `${(b.aborted / b.count) * 100}%` }" />
          </div>
          <div class="mlist">
            <button v-for="id in b.machine_ids" :key="id" class="mchip" :class="{ bad: !!blockReason(machineOf(id)) }" @click="router.push({ path: '/overview', query: { m: id } })" v-tip="blockReason(machineOf(id)) || `${machineOf(id).slots.filter((s) => s.phase === 'SAMPLING').length} 个槽位采样中`">
              <b class="mono">{{ id }}</b>
              <span class="mini"><i v-for="s in machineOf(id).slots" :key="s.index" :class="s.phase === 'SAMPLING' ? 'on' : s.phase === 'ERROR' ? 'err' : ''" /></span>
            </button>
          </div>
        </div>
      </Panel>

      <Panel title="实时测试记录" code="RUNS · STREAM" :icon="ListChecks" flush>
        <template #actions><button class="btn btn-ghost btn-sm" @click="tab = 'runs'">全部记录<ArrowRight :size="14" /></button></template>
        <div class="table-wrap" style="border-top: 0">
          <table class="table">
            <thead><tr><th>结束时间</th><th>run_id</th><th>机台#槽位</th><th>序列号</th><th>判定</th><th>不合格项</th><th class="r">Rc ℃/W</th><th class="r">T0−T1 ℃</th></tr></thead>
            <tbody>
              <TransitionGroup name="row">
                <tr v-for="r in stream" :key="r.run_id">
                  <td class="num fs-sm">{{ hms(r.ended_at) }}</td>
                  <td class="mono fs-xs">{{ r.run_id }}</td>
                  <td class="mono">{{ r.machine_id }}#{{ r.slot_index }}</td>
                  <td class="mono fs-xs">{{ r.serial_number }}</td>
                  <td><StatusTag :status="runTag(r)" /></td>
                  <td class="mono fs-xs" :class="{ 't-danger': r.fail_items.length }">{{ r.fail_items.join(', ') || '—' }}</td>
                  <td class="r num">{{ r.rc?.toFixed(3) ?? '—' }}</td>
                  <td class="r num">{{ r.dt01?.toFixed(3) ?? '—' }}</td>
                </tr>
              </TransitionGroup>
            </tbody>
          </table>
        </div>
      </Panel>
    </template>

    <!-- 历史批次 -->
    <Panel v-else-if="tab === 'history'" flush>
      <div class="toolbar">
        <div class="input-wrap" style="width: 260px"><Search :size="14" /><input v-model="kw" class="input" placeholder="批次号 / 型号" aria-label="搜索批次" /></div>
        <Filter :size="14" class="muted" />
        <select v-model="modelFilter" class="select" aria-label="按型号筛选">
          <option value="all">全部型号</option>
          <option v-for="m in productModels" :key="m.model" :value="m.model">{{ m.model }}</option>
        </select>
        <span class="grow" />
        <template v-if="selected.length">
          <span class="fs-sm">已选 <b class="num">{{ selected.length }}</b> 个批次</span>
          <button class="btn btn-ghost btn-sm" @click="selected = []"><X :size="14" />清除</button>
        </template>
        <span v-tip="selected.length < 2 ? '勾选 2 个及以上批次可合并生成报告' : ''">
          <button class="btn btn-primary" :disabled="selected.length < 2" @click="report(selected)"><FileStack :size="16" />合并生成报告{{ selected.length >= 2 ? `（${selected.length}）` : '' }}</button>
        </span>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th style="width: 36px"><input type="checkbox" :checked="allChecked" aria-label="全选" @change="toggleAll" /></th>
              <th>批次号</th><th>型号</th><th>方案</th><th>状态</th><th style="width: 150px">进度</th><th class="r">良率</th><th class="r">Rc 均值 ± σ</th><th>主要不合格项</th><th>机台</th><th>开始</th><th class="r">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in history" :key="b.batch_id" :class="{ 'is-selected': selected.includes(b.batch_id) }">
              <td><input type="checkbox" :checked="selected.includes(b.batch_id)" :aria-label="`选择 ${b.batch_id}`" @change="toggle(b.batch_id)" /></td>
              <td class="mono fw-6 fs-sm">{{ b.batch_id }}</td>
              <td>{{ b.model }}</td>
              <td class="fs-sm">{{ planLabel(b.plan_id, b.plan_version) }}</td>
              <td><StatusTag :status="b.state === 'running' ? 'RUNNING' : b.state === 'done' ? 'done' : 'stopped'" /></td>
              <td>
                <div class="bar"><i :style="{ width: `${(b.tested / b.count) * 100}%` }" /></div>
                <span class="fs-xs muted num">{{ b.tested }} / {{ b.count }}</span>
              </td>
              <td class="r num" :class="yieldOf(b) < 97 ? 't-danger fw-6' : ''">{{ yieldOf(b).toFixed(2) }}%</td>
              <td class="r num">{{ b.rc_mean.toFixed(3) }} ± {{ b.rc_sd.toFixed(3) }}</td>
              <td class="mono fs-xs">{{ b.top_fail }}</td>
              <td class="fs-xs muted">{{ b.machine_ids.length }} 台</td>
              <td class="num fs-sm">{{ dt(b.started_at) }}</td>
              <td class="r"><button class="btn btn-sm" :disabled="!b.tested" @click="report([b.batch_id])"><FileText :size="14" />报告</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>

    <!-- 测试记录 -->
    <Panel v-else flush>
      <div class="toolbar">
        <button class="btn btn-primary" :disabled="!reportBatches.length" @click="report(reportBatches)"><FileText :size="16" />打开批次报告（{{ reportBatches.length }}）</button>
        <div class="input-wrap" style="width: 280px"><Search :size="14" /><input v-model="rf.kw" class="input" placeholder="run_id / 序列号" aria-label="搜索测试记录" /></div>
        <select v-model="rf.machine" class="select" aria-label="机台">
          <option value="all">全部机台</option>
          <option v-for="m in machines" :key="m.machine_id" :value="m.machine_id">{{ m.machine_id }}</option>
        </select>
        <div class="seg">
          <button v-for="o in (['all', 'pass', 'fail', 'none'] as const)" :key="o" :aria-pressed="rf.passed === o" @click="rf.passed = o">{{ { all: '全部', pass: '合格', fail: '不合格', none: '中止 / 故障' }[o] }}</button>
        </div>
        <span class="grow" />
        <span class="fs-xs muted">显示最近 {{ runList.length }} 条</span>
      </div>
      <div class="table-wrap" style="max-height: calc(100vh - 300px)">
        <table class="table">
          <thead><tr><th>结束时间</th><th>run_id</th><th>机台#槽位</th><th>序列号</th><th>方案</th><th>状态 / 判定</th><th>不合格项</th><th>结果行</th><th class="r">Rc</th><th class="r">T0−T1</th></tr></thead>
          <tbody>
            <tr v-for="r in runList" :key="r.run_id" class="clickable" :class="{ 'is-selected': selectedId === r.run_id }" @click="openRun(r.run_id)">
              <td class="num fs-sm">{{ dt(r.ended_at) }}</td>
              <td class="mono fs-xs">{{ r.run_id }}</td>
              <td class="mono">{{ r.machine_id }}#{{ r.slot_index }}</td>
              <td class="mono fs-xs">{{ r.serial_number }}</td>
              <td class="fs-xs">{{ planLabel(r.plan_id, r.plan_version) }}</td>
              <td><StatusTag :status="runTag(r)" /></td>
              <td class="mono fs-xs" :class="{ 't-danger': r.fail_items.length }">{{ r.fail_items.join(', ') || '—' }}</td>
              <td><span class="tag" :class="r.keep_result ? '' : 'warn'">{{ r.keep_result ? '已保留' : '丢失' }}</span></td>
              <td class="r num">{{ r.rc?.toFixed(3) ?? '—' }}</td>
              <td class="r num">{{ r.dt01?.toFixed(3) ?? '—' }}</td>
            </tr>
            <tr v-if="!runList.length"><td colspan="10" class="c muted" style="height: 80px">没有符合条件的测试记录</td></tr>
          </tbody>
        </table>
      </div>
    </Panel>

    <Transition name="dr">
      <div v-if="selectedId" class="mask" @mousedown.self="selectedId = null">
        <aside class="drawer" role="dialog" :aria-label="`测试记录 ${selectedId}`">
          <header class="dh">
            <div class="grow">
              <h2 class="mono">{{ selectedId }}</h2>
              <span class="fs-xs muted">判定结果、过程曲线、仿真真值</span>
            </div>
            <button class="btn btn-ghost btn-icon" v-tip="'关闭'" @click="selectedId = null"><X :size="18" /></button>
          </header>
          <div class="db">
            <p v-if="detailError" class="fs-sm t-danger">{{ detailError }}</p>
            <section v-if="detail">
              <h4>判定结果</h4>
              <div class="json">
                <div class="fw-6" :class="detailVerdict === 'pass' ? 't-ok' : 't-danger'">测试结果：{{ detailVerdict }}</div>
                <div v-if="detailVerdict === 'fail' && failItems.length && !deltaRows.some((row) => row.fail)" class="t-danger fw-6">{{ failItems.join(', ') }}</div>
                <div v-for="row in deltaRows" :key="row.key" :class="{ 't-danger fw-6': row.fail }">{{ row.key }}: {{ row.value }}</div>
              </div>
            </section>
            <section>
              <h4>过程曲线</h4>
              <EChart v-if="samplePoints.length" :option="curveOpt" :height="240" />
              <p v-else class="fs-sm muted">{{ samplesHint }}</p>
            </section>
            <section>
              <h4>仿真真值 · 仅算法评估</h4>
              <p v-if="gtHint" class="fs-sm muted">{{ gtHint }}</p>
              <div v-else-if="gt" class="json">
                <div>型号 {{ gt.model || '—' }} · 等级 {{ gt.grade || '—' }} · quality {{ gt.quality?.toFixed(3) ?? '—' }}</div>
                <div>接触 {{ gt.contact_quality?.toFixed(3) ?? '—' }} · 场景 {{ gt.scenario_id || '—' }}</div>
                <div v-if="gt.fault_kinds?.length">故障 {{ gt.fault_kinds.join(', ') }}</div>
                <div v-for="(defect, index) in (gt.defects || [])" :key="index">缺陷 {{ defect.kind }} · severity {{ defect.severity }}</div>
              </div>
            </section>
          </div>
        </aside>
      </div>
    </Transition>

    <!-- 新建测试任务抽屉 -->
    <Transition name="dr">
      <div v-if="open" class="mask" @mousedown.self="open = false">
        <aside class="drawer" role="dialog" aria-label="新建测试任务">
          <header class="dh">
            <Send :size="18" class="t-primary" />
            <div class="grow">
              <h2>新建测试任务</h2>
              <span class="fs-xs muted mono">POST /api/v1/production/start</span>
            </div>
            <button class="btn btn-ghost btn-icon" v-tip="'关闭'" @click="open = false"><X :size="18" /></button>
          </header>
          <div class="db">
            <section>
              <h4><span class="n">1</span>测试方案</h4>
              <div class="row">
                <select v-model="form.plan_id" class="select grow" aria-label="测试方案">
                  <option v-for="p in published" :key="p.plan_id" :value="p.plan_id">{{ p.name }} · {{ p.plan_id }}</option>
                </select>
                <select v-model.number="form.plan_version" class="select" style="width: 90px" aria-label="版本">
                  <option v-for="v in versions" :key="v" :value="v">v{{ v }}</option>
                </select>
                <button class="btn btn-ghost btn-sm" @click="router.push({ path: '/plans', query: { p: form.plan_id } })">查看</button>
              </div>
              <div v-if="plan" class="kvg">
                <span>起始温度 <b class="num">{{ plan.start_temp_c }} ℃</b></span>
                <span>测量时长 <b class="num">{{ plan.duration_s }} s</b></span>
                <span>功率 <b class="num">{{ plan.power_w }} W</b></span>
                <span>压紧力 <b class="num">{{ plan.force_g }} g</b></span>
                <span>朝向 <b class="num">{{ plan.orientation }}°</b></span>
                <span>判定项 <b class="num">{{ plan.limits.filter((l) => !l.skipped).length }}</b></span>
              </div>
            </section>

            <section>
              <h4><span class="n">2</span>均热板来源</h4>
              <div class="seg">
                <button :aria-pressed="form.source === 'batch'" @click="form.source = 'batch'">按批次</button>
                <button :aria-pressed="form.source === 'serials'" @click="form.source = 'serials'">按序列号</button>
              </div>
              <template v-if="form.source === 'batch'">
                <select v-model="form.batch_id" class="select" aria-label="批次">
                  <option v-for="b in batches" :key="b.batch_id" :value="b.batch_id" :disabled="!remaining(b.batch_id)">{{ b.batch_id }} · {{ b.model }} · 待测 {{ remaining(b.batch_id) }} / {{ b.count }} 片</option>
                </select>
                <span class="fs-xs muted">待测（state = NEW）<b class="num">{{ newCount }}</b> 片 · 型号参考功率 {{ model?.power_w ?? '—' }} W</span>
              </template>
              <textarea v-else v-model="form.serials" class="textarea mono" rows="3" placeholder="每行一个序列号，或用逗号分隔；只会取状态为 NEW 的均热板" />
            </section>

            <section>
              <h4 class="row-between"><span><span class="n">3</span>机台</span><button class="btn btn-ghost btn-sm" @click="selectAvailable">选择全部可用</button></h4>
              <div class="mgrid">
                <label v-for="m in machines" :key="m.machine_id" class="mopt" :class="{ on: form.machine_ids.includes(m.machine_id), dis: !!blockReason(m) }" v-tip="blockReason(m) || warnReason(m)">
                  <input type="checkbox" :checked="form.machine_ids.includes(m.machine_id)" :disabled="!!blockReason(m)" @change="toggleMachine(m.machine_id)" />
                  <b class="mono">{{ m.machine_id }}</b>
                  <StatusTag :status="m.comm_status === 'DISCONNECTED' ? 'DISCONNECTED' : m.status" />
                  <CircleAlert v-if="warnReason(m) && !blockReason(m)" :size="13" class="t-warn" />
                </label>
              </div>
            </section>

            <section>
              <h4><span class="n">4</span>运行选项</h4>
              <label class="opt"><input v-model="form.auto_recover" type="checkbox" /><span><b>自动恢复</b><span class="fs-xs muted" style="display: block">槽位 ERROR / 机台 FAULT 时，等待后自动清错复位继续；关闭则在故障处停止</span></span></label>
              <div class="field">
                <label for="mc">最大测试次数</label>
                <input id="mc" v-model.number="form.max_count" class="input num" type="number" min="1" placeholder="留空表示不限制" style="width: 200px" />
              </div>
            </section>

            <section>
              <h4><span class="n">5</span>下发前校验</h4>
              <ul class="checks">
                <li v-for="c in checks" :key="c.text" :class="c.level"><i />{{ c.text }}</li>
              </ul>
              <button class="btn btn-ghost btn-sm" style="align-self: flex-start" :aria-expanded="showBody" @click="showBody = !showBody"><Code :size="14" />请求体<ChevronDown :size="14" :style="{ transform: showBody ? 'rotate(180deg)' : '' }" /></button>
              <pre v-if="showBody" class="json">{{ JSON.stringify(body, null, 2) }}</pre>
            </section>
          </div>
          <footer class="df">
            <span class="fs-xs muted grow">关机的机台会先自动上电；方案版本不一致的会先下发</span>
            <button class="btn" @click="open = false">取消</button>
            <button class="btn btn-primary" :disabled="blocked" @click="submit"><Send :size="16" />{{ starting ? '下发中' : '下发并开始' }}</button>
          </footer>
        </aside>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.tabs { display: flex; border-bottom: var(--bw) solid var(--c-border-strong); }
.tabs button { display: inline-flex; align-items: center; gap: 6px; height: 40px; padding: 0 16px; border: 0; background: transparent; color: var(--c-text-2); cursor: pointer; border-bottom: 3px solid transparent; margin-bottom: -1px; font-size: var(--fs-md); }
.tabs button:hover { color: var(--c-text); }
.tabs button[aria-selected='true'] { color: var(--c-text); font-weight: 700; border-bottom-color: var(--c-primary); }

.empty { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 48px; background: var(--c-surface); border: var(--bw) dashed var(--c-border-strong); color: var(--c-text-2); }
.bh { display: flex; align-items: center; gap: 8px; padding: 14px; flex-wrap: wrap; }
.prog { padding: 0 14px 14px; display: flex; flex-direction: column; gap: 8px; }
.stack { position: relative; display: flex; height: 10px; background: var(--c-surface-3); }
.stack i { height: 100%; transition: width 400ms var(--ease); }
.stack .p { background: var(--c-ok); }
.stack .f { background: var(--c-danger); }
.stack .a { background: var(--c-warn); }
.mlist { display: flex; flex-wrap: wrap; gap: 6px; }
.mchip { display: flex; align-items: center; gap: 6px; padding: 4px 8px; background: var(--c-surface-2); border: var(--bw) solid var(--c-border); cursor: pointer; }
.mchip:hover { border-color: var(--c-text-2); }
.mchip.bad { border-color: var(--c-danger); background: var(--c-danger-weak); }
.mini { display: inline-grid; grid-template-columns: repeat(10, 5px); gap: 1px; }
.mini i { height: 12px; background: var(--c-surface-3); }
.mini i.on { background: var(--c-primary); }
.mini i.err { background: var(--c-danger); }

.toolbar { display: flex; align-items: center; gap: 8px; padding: 10px 12px; flex-wrap: wrap; }
.table input[type='checkbox'], .mopt input, .opt input { accent-color: var(--c-primary); }
.row-enter-from { background: var(--c-primary-weak); }
.row-enter-active { transition: background-color 1.2s var(--ease); }

.mask { position: fixed; inset: 0; z-index: 80; background: rgba(12, 16, 20, 0.3); display: flex; justify-content: flex-end; }
.drawer { width: min(640px, 94vw); height: 100%; background: var(--c-surface); border-left: 3px solid var(--c-primary); box-shadow: var(--shadow-pop); display: flex; flex-direction: column; }
.dh { display: flex; align-items: center; gap: 10px; padding: 14px 14px 12px 16px; border-bottom: var(--bw) solid var(--c-border); }
.dh h2 { font-size: var(--fs-lg); }
.db { flex: 1; overflow: auto; padding: 4px 16px 16px; }
.db section { display: flex; flex-direction: column; gap: 8px; padding: 14px 0; border-bottom: var(--bw) solid var(--c-border); }
.db h4 { font-size: var(--fs-md); display: flex; align-items: center; gap: 8px; }
.db h4 .n { display: inline-grid; place-items: center; width: 20px; height: 20px; background: var(--c-accent); color: #fff; font-family: var(--font-mono); font-size: 11px; margin-right: 8px; }
.kvg { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--c-border); border: var(--bw) solid var(--c-border); }
.kvg span { background: var(--c-surface-2); padding: 6px 10px; font-size: var(--fs-xs); color: var(--c-text-3); display: flex; justify-content: space-between; }
.kvg b { color: var(--c-text); font-size: var(--fs-sm); }
.mgrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.mopt { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border: var(--bw) solid var(--c-border); background: var(--c-surface); cursor: pointer; }
.mopt:hover { border-color: var(--c-text-2); }
.mopt.on { border-color: var(--c-primary); background: var(--c-primary-weak); }
.mopt.dis { cursor: not-allowed; opacity: 0.55; background: var(--c-surface-2); }
.opt { display: flex; gap: 8px; align-items: flex-start; cursor: pointer; }
.opt input { margin-top: 4px; }
.checks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.checks li { display: flex; align-items: center; gap: 8px; padding: 6px 10px; font-size: var(--fs-sm); background: var(--c-ok-weak); }
.checks li i { width: 8px; height: 8px; background: var(--c-ok); flex: none; }
.checks li.warn { background: var(--c-warn-weak); } .checks li.warn i { background: var(--c-warn); }
.checks li.danger { background: var(--c-danger-weak); color: var(--c-danger); } .checks li.danger i { background: var(--c-danger); }
.json { margin: 0; padding: 10px 12px; background: var(--c-surface-2); border: var(--bw) solid var(--c-border); font-family: var(--font-mono); font-size: 12px; overflow: auto; }
.df { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-top: var(--bw) solid var(--c-border); background: var(--c-surface-2); }
.dr-enter-active, .dr-leave-active { transition: opacity 160ms var(--ease); }
.dr-enter-active .drawer, .dr-leave-active .drawer { transition: transform 200ms var(--ease); }
.dr-enter-from, .dr-leave-to { opacity: 0; }
.dr-enter-from .drawer, .dr-leave-to .drawer { transform: translateX(40px); }
</style>
