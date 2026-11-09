<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, BarChart3, Bot, Download, Loader2, Sparkles } from 'lucide-vue-next'
import Kpi from '@/components/Kpi.vue'
import Panel from '@/components/Panel.vue'
import EChart from '@/components/EChart.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api, apiBlob, currentToken } from '@/api/http'
import { useAppStore } from '@/stores/app'
import { useTokens } from '@/composables/useTokens'
import { dt } from '@/utils/format'

interface ReportBatch {
  batch_id: string
  model: string
  plan_id: string
  plan_version: number
  plan_name: string
  tested: number
  passed: number
  failed: number
  aborted: number
  yield_rate?: number
  rc_mean: number
  rc_sd: number
  top_fail: string
  top_fail_count?: number
  cpk_t01?: number | null
  worst_machine_id?: string
  worst_machine_n?: number
  worst_machine_passed?: number
  started_at: number
  state: 'running' | 'done' | 'stopped'
}
interface ReportData {
  batches: ReportBatch[]
  summary: {
    tested: number
    passed: number
    failed: number
    aborted: number
    yield_rate: number
    rc_mean: number
    rc_sd: number
    cpk_t01: number | null
    usl_t01: number | null
    machine_count: number
  }
  machine_yield: { machine_id: string; n: number; passed: number }[]
  rc_histogram: { edges: number[]; counts: Record<string, number[]> }
  ambient?: { batch_id: string; serial: string; ended_at: number; machine_id: string; slot_index: number; value: number | null; t01: number | null }[]
  fail_pareto: { item: string; count: number }[]
  delta_profile: { items: string[]; mean: Record<string, (number | null)[]>; p95?: (number | null)[]; limit: (number | null)[] }
  compare: { batch_id: string; yield_rate: number; rc_mean: number }[]
}

const route = useRoute()
const router = useRouter()
const app = useAppStore()
const tk = useTokens()
const report = ref<ReportData | null>(null)
const error = ref('')
const loading = ref(false)
const asked = computed(() => String(route.query.b ?? '').split(',').map((id) => id.trim()).filter(Boolean))
interface LimitItem {
  item: string
  n: number
  mean: number | null
  minimum: number | null
  maximum: number | null
  range: number | null
  std: number | null
  low: number | null
  high: number | null
  high_fail: number
  low_fail: number
  offset: string
  margin_high: number | null
  margin_low: number | null
  cpk: number | null
  repeat_std: number | null
  retest_serials: number
  retest_range: number | null
  trend: string
  invalid: number
}
interface FailGroup { items: string[]; count: number }
interface AnalysisSlice { name: string; aborted: number; discarded: number; invalid: number; items: LimitItem[]; correlations: { left: string; right: string; r: number | null; n: number; co_fail: number }[]; fail_groups?: FailGroup[] }
interface AnalysisData {
  note: string
  tested: number
  aborted: number
  discarded: number
  invalid: number
  fail_rank: { item: string; count: number }[]
  fail_groups: { items: string[]; count: number }[]
  overall: AnalysisSlice
  batches: AnalysisSlice[]
  machines: AnalysisSlice[]
  slots: AnalysisSlice[]
  census?: { batch: string; tested: number; passed: number; slots: { slot: string; tested: number; passed: number }[] }[]
  process: { serial_number: string; item: string; shape: string }[]
}
const analysis = ref<AnalysisData | null>(null)
const analysisTarget = ref<'product' | 'machine'>('product')
const summaryLines = ref<string[]>([])
const summaryModel = ref('')
const summaryError = ref('')
const summaryBusy = ref(false)
const summaryMode = ref<'single' | 'cross' | ''>('')
const summaryOpen = ref(true)
const summaryLooked = ref('')
function summaryLead(line: string) {
  if (line === '已暴露的卡限项' || line === '潜在危险项') return line
  const parts = line.split(/(?<=。)/)
  let lead = ''
  for (const part of parts) {
    if (part.includes('怀疑产品问题') || part.includes('怀疑这台机') || part.includes('怀疑这些槽位')) lead += part
    else break
  }
  return lead
}
function summaryBreak(line: string, index: number) {
  return index > 0 && (summaryLead(line) !== '' || line.startsWith('先看超限项') || line.startsWith('按同一项对齐') || /^(Temp_|室温|power_w)/.test(line))
}
interface FigurePanel {
  title: string
  option: Record<string, unknown>
}
interface FigureQuestion {
  text: string
  options: string[]
}
interface FigureTable {
  name: string
  columns: string[]
  rows: string[][]
}
interface FigureItem {
  figure_id: string
  status: string
  prompt: string
  title: string
  echarts_option: Record<string, unknown> | null
  panels: FigurePanel[]
  png_url: string | null
  code: string
  results: string[][]
  summary?: { scope: string; columns: string[]; rows: string[][]; notes: string[] } | null
  table?: FigureTable | null
  questions?: FigureQuestion[]
  note?: string
  error: string | null
  step: string
}
const figurePresets = [
  { id: 'slot_rc', label: '槽位箱线' },
  { id: 'scatter', label: '分项分布' },
  { id: 'pareto', label: '超限片数' },
  { id: 'trend', label: '温差走势' },
  { id: 'heatmap', label: '机台×槽位' },
  { id: 'compare', label: '同项对比' },
]
const figures = ref<FigureItem[]>([])
const figurePrompt = ref('')
const figureBusy = ref(false)
const figureError = ref('')
const pngUrls = ref<Record<string, string>>({})
const figureOpen = ref<Record<string, boolean>>({})
const tableOpen = ref<Record<string, boolean>>({})
const replyText = ref<Record<string, string>>({})
const replyPicks = ref<Record<string, string[]>>({})

async function load() {
  if (!asked.value.length) {
    report.value = null
    error.value = '没有指定批次'
    return
  }
  loading.value = true
  error.value = ''
  analysis.value = null
  summaryLines.value = []
  summaryModel.value = ''
  summaryLooked.value = ''
  summaryError.value = ''
  summaryMode.value = ''
  figures.value = []
  figureError.value = ''
  try {
    const query = encodeURIComponent(asked.value.join(','))
    report.value = await api<ReportData>(`/reports/data?batch_ids=${query}`)
    analysis.value = await api<AnalysisData>(`/reports/analysis?batch_ids=${query}`).catch(() => null)
    await loadFigures().catch(() => { figures.value = [] })
  } catch (err) {
    report.value = null
    error.value = err instanceof Error ? err.message : '报告加载失败'
  } finally {
    loading.value = false
  }
}
watch(() => route.query.b, load, { immediate: true })

function num(value: number | null | undefined) {
  return value == null ? '—' : value.toFixed(3)
}
function meas(item: string, value: number | null | undefined) {
  const text = num(value)
  if (text === '—') return text
  if (item === 'power_w') return `${text} W`
  if (item.startsWith('Temp_')) return `${text} ℃`
  return text
}
const shownSlices = computed(() => analysisTarget.value === 'product' ? (analysis.value?.batches ?? []) : (analysis.value?.machines ?? []))
const acrossSlices = computed(() => {
  const data = analysis.value
  if (!data) return []
  if (analysisTarget.value === 'product') return data.batches
  return data.slots.length ? data.slots : data.machines
})
const acrossLabel = computed(() => {
  if (analysisTarget.value === 'product') return '各批次'
  return analysis.value?.slots.length ? '各槽位' : '各机台'
})
function yieldText(passed: number, tested: number) {
  if (!tested) return '—'
  return `${(100 * passed / tested).toFixed(2)}%`
}
const censusTables = computed(() => (analysis.value?.census ?? []).map((batch) => {
  const slots = batch.slots.map((slot) => {
    const [machine, index] = slot.slot.split('#')
    return { slot: slot.slot, machine: machine || slot.slot, index: index || '—', tested: slot.tested, yield: yieldText(slot.passed, slot.tested) }
  })
  return {
    batch: batch.batch,
    machines: [...new Set(slots.map((slot) => slot.machine))].join('、') || '—',
    tested: batch.tested,
    yield: yieldText(batch.passed, batch.tested),
    slots,
  }
}))
function sliceItem(slice: AnalysisSlice, name: string) {
  return slice.items.find((item) => item.item === name)
}
function overallItem(name: string) {
  return analysis.value?.overall.items.find((item) => item.item === name)
}
function limitCell(name: string, side: 'low' | 'high') {
  const heads = compareHeads.value
  if (heads.length > 1) {
    const parts = heads.map((head) => ({ label: head.label, value: sliceItem(head.slice, name)?.[side] }))
    const known = parts.filter((part) => part.value != null)
    if (!known.length) return '—'
    const first = known[0].value
    if (known.length === parts.length && known.every((part) => part.value === first)) return meas(name, first)
    return known.map((part) => `${part.label} ${meas(name, part.value)}`).join(' · ')
  }
  return meas(name, overallItem(name)?.[side])
}
function itemKey(name: string): [number, number, number, string] {
  const bare = name.replace(/^Temp_/i, '')
  const delta = bare.match(/^T(\d+)-T(\d+)$/i)
  if (delta) return [0, Number(delta[1]), Number(delta[2]), name]
  const point = bare.match(/^T(\d+)$/i)
  if (point) return [0, Number(point[1]), -1, name]
  if (name === 'power_w') return [4, 0, 0, name]
  return [9, 0, 0, name]
}
const failText = computed(() => {
  const data = analysis.value
  if (!data) return ''
  const groups = data.fail_groups ?? []
  const failed = groups.reduce((sum, group) => sum + group.count, 0)
  const passed = Math.max(data.tested - failed, 0)
  const parts = [`测了 ${data.tested} 片`]
  if (passed) parts.push(`合格 ${passed} 片`)
  for (const group of groups) {
    const names = group.items.join('、')
    parts.push(group.items.length === 1 ? `单项不合格 ${names} 有 ${group.count} 片` : `多项不合格 ${names} 有 ${group.count} 片`)
  }
  if (!groups.length) parts.push('卡限项都合格')
  return `${parts.join('，')}。`
})
const batchMarks = ['一', '二', '三', '四', '五', '六']
const showQuiet = ref(false)
const censusOpen = ref(false)
function pieceCount(slice: AnalysisSlice) {
  return slice.items.reduce((max, item) => Math.max(max, item.n), 0)
}
const compareHeads = computed(() => {
  const slices = acrossSlices.value
  const kind = analysisTarget.value === 'product' ? '批次' : (analysis.value?.slots.length ? '槽位' : '机台')
  return slices.map((slice, index) => ({
    label: `${kind}${batchMarks[index] ?? index + 1}`,
    name: slice.name,
    n: pieceCount(slice),
    color: tk.value.chart[index % 6],
    slice,
  }))
})
function itemNotable(item: LimitItem | undefined) {
  if (!item) return false
  if (item.high_fail || item.low_fail) return true
  if (item.margin_high != null && item.margin_high < 0.3) return true
  return item.trend === '后半段升高' || item.trend === '后半段降低'
}
function rangeSplit(name: string) {
  const rows = compareHeads.value
    .map((head) => sliceItem(head.slice, name))
    .filter((item): item is LimitItem => !!item && item.n >= 30 && item.range != null)
  if (rows.length < 2) return false
  const ranges = rows.map((item) => item.range as number)
  const low = Math.min(...ranges)
  return low > 0 && Math.max(...ranges) >= low * 2
}
function rowNotable(name: string) {
  if (compareHeads.value.length > 1) return compareHeads.value.some((head) => itemNotable(sliceItem(head.slice, name))) || rangeSplit(name)
  return itemNotable(analysis.value?.overall.items.find((item) => item.item === name))
}
const visibleItemNames = computed(() => {
  const names = orderedItemNames.value
  if (showQuiet.value) return names
  const kept = names.filter(rowNotable)
  return kept.length ? kept : names
})
const hiddenCount = computed(() => orderedItemNames.value.filter((name) => !rowNotable(name)).length)
function failClass(value: number | undefined) {
  return value ? 't-danger' : ''
}
function marginClass(value: number | null | undefined) {
  return value != null && value < 0.3 ? 'cell-warn' : ''
}
function countClass(value: number | undefined) {
  return value != null && value > 0 && value < 30 ? 'muted' : ''
}
function rangeClass(name: string, item: LimitItem | undefined) {
  if (!item?.range || !rangeSplit(name)) return ''
  const ranges = compareHeads.value.map((head) => sliceItem(head.slice, name)?.range ?? 0)
  return item.range >= Math.max(...ranges) ? 'cell-warn' : ''
}
function scaledNames(names: string[]) {
  const temps = names.filter((name) => name.startsWith('Temp_'))
  return temps.length ? temps : names
}
function detailTip(name: string) {
  const heads = compareHeads.value
  if (heads.length < 2) return name
  const lines = [name]
  for (const head of heads) {
    const item = sliceItem(head.slice, name)
    if (!item) {
      lines.push(`${head.label} ${head.name} 没有这项`)
      continue
    }
    lines.push(`${head.label} ${head.name} ${item.n} 片 均值 ${meas(name, item.mean)} 最小 ${meas(name, item.minimum)} 最大 ${meas(name, item.maximum)} 上限 ${meas(name, item.high)} 下限 ${meas(name, item.low)} 超上限 ${item.high_fail} 片 超下限 ${item.low_fail} 片`)
  }
  return lines.join('<br/>')
}
const orderedItemNames = computed(() => [...(analysis.value?.overall.items ?? [])].map((item) => item.item).sort((left, right) => {
  const a = itemKey(left)
  const b = itemKey(right)
  return a[0] - b[0] || a[1] - b[1] || a[2] - b[2] || a[3].localeCompare(b[3])
}))

function batchYield(batch: { passed: number; tested: number; yield_rate?: number }) {
  if (batch.tested <= 0) return '—'
  const rate = typeof batch.yield_rate === 'number' ? batch.yield_rate : (100 * batch.passed) / batch.tested
  return `${rate.toFixed(2)}%`
}

const list = computed(() => report.value?.batches ?? [])
const sum = computed(() => report.value?.summary)
const multi = computed(() => list.value.length > 1)
const skipped = computed(() => asked.value.filter((id) => !list.value.some((batch) => batch.batch_id === id)))
const hasRc = computed(() => (report.value?.rc_histogram.edges.length ?? 0) > 0)

const findings = computed(() => {
  if (!report.value) return []
  return list.value.map((batch) => ({ batch_id: batch.batch_id, lines: batchLines(batch) }))
})

function batchLines(batch: ReportBatch) {
  if (batch.tested <= 0) return ['这个批次还没有测完的片子。']
  const rate = typeof batch.yield_rate === 'number' ? batch.yield_rate : (100 * batch.passed) / batch.tested
  const lines = [`测了 ${batch.tested} 片：合格 ${batch.passed}，不合格 ${batch.failed}，中止 ${batch.aborted}，良率 ${rate.toFixed(2)}%。`]
  const slice = analysis.value?.batches.find((item) => item.name === batch.batch_id)
  const groups = slice?.fail_groups ?? []
  if (groups.length) {
    lines.push(`${groups.map((group) => group.items.length === 1 ? `单项不合格 ${group.items[0]} 有 ${group.count} 片` : `多项不合格 ${group.items.join('、')} 有 ${group.count} 片`).join('，')}。`)
  } else if (!batch.failed && !batch.aborted) lines.push('没有不合格，也没有中止。')
  if (batch.worst_machine_id && batch.worst_machine_n) {
    lines.push(`${batch.worst_machine_id} 良率最低，${batch.worst_machine_passed ?? 0}/${batch.worst_machine_n}。`)
  }
  const power = slice?.items.find((item) => item.item === 'power_w')
  if (power) lines.push(`功率均值 ${meas('power_w', power.mean)}，极差 ${meas('power_w', power.range)}。`)
  const delta = slice?.items.find((item) => item.item === 'Temp_T0-T1')
  if (delta) lines.push(`Temp_T0-T1 均值 ${meas(delta.item, delta.mean)}，最大值 ${meas(delta.item, delta.maximum)}，最小值 ${meas(delta.item, delta.minimum)}，极差 ${meas(delta.item, delta.range)}。`)
  const limited = (slice?.items ?? []).filter((item) => { const key = itemKey(item.item); return key[0] === 0 && key[2] >= 0 && item.mean != null })
  if (limited.length) {
    const hottestItem = limited.reduce((best, item) => (item.mean ?? 0) > (best.mean ?? 0) ? item : best)
    const coolestItem = limited.reduce((best, item) => (item.mean ?? 0) < (best.mean ?? 0) ? item : best)
    lines.push(`卡限温差里，均值的最大值是 ${hottestItem.item}，${meas(hottestItem.item, hottestItem.mean)}。最小值是 ${coolestItem.item}，${meas(coolestItem.item, coolestItem.mean)}。`)
  }
  return lines
}

async function loadSavedSummary() {
  const body = await api<{ lines: string[]; model: string }>(`/reports/summary?batch_ids=${encodeURIComponent(asked.value.join(','))}`)
  summaryLines.value = body.lines || []
  summaryModel.value = body.model || ''
}

async function loadSummary(mode: 'single' | 'cross') {
  if (!asked.value.length || summaryBusy.value) return
  if (mode === 'cross' && list.value.length < 2) return
  summaryOpen.value = true
  summaryBusy.value = true
  summaryMode.value = mode
  summaryError.value = ''
  summaryLines.value = []
  summaryLooked.value = ''
  try {
    const body = await api<{ lines: string[]; model: string; looked?: string }>('/reports/summary', {
      method: 'POST',
      body: JSON.stringify({ batch_ids: asked.value, mode }),
    })
    summaryLines.value = body.lines
    summaryModel.value = body.model
    summaryLooked.value = body.looked || ''
  } catch (err) {
    summaryLines.value = []
    summaryModel.value = ''
    summaryLooked.value = ''
    summaryError.value = err instanceof Error ? err.message : '分析没有生成'
  } finally {
    summaryBusy.value = false
  }
}

async function loadFigures() {
  if (!asked.value.length) return
  figures.value = await api<FigureItem[]>(`/reports/figures?batch_ids=${encodeURIComponent(asked.value.join(','))}`)
  await Promise.all(figures.value.map((item) => attachPng(item)))
}

async function createFigure(preset = '') {
  const kind = typeof preset === 'string' ? preset : ''
  const prompt = kind ? '' : figurePrompt.value.trim()
  if ((!prompt && !kind) || figureBusy.value || !asked.value.length) return
  figureBusy.value = true
  figureError.value = ''
  let createdId = ''
  try {
    const created = await api<{ figure_id: string }>('/reports/figures', {
      method: 'POST',
      body: JSON.stringify({ batch_ids: asked.value, prompt, preset: kind }),
    })
    createdId = created.figure_id
    if (!kind) figurePrompt.value = ''
    const previous = figures.value[0]?.figure_id
    await loadFigures()
    figureOpen.value = { ...figureOpen.value, [created.figure_id]: true }
    if (previous && previous !== created.figure_id) figureOpen.value = { ...figureOpen.value, [previous]: false }
  } catch (err) {
    figureError.value = err instanceof Error ? err.message : '分析没有开始'
    return
  } finally {
    figureBusy.value = false
  }
  if (createdId) await followFigure(createdId)
}

async function followFigure(id: string) {
  const token = currentToken()
  if (!token) return
  const res = await fetch(`/api/v1/reports/figures/${id}/events`, { headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok || !res.body) {
    await refreshFigure(id)
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const chunk = await reader.read()
    if (chunk.done) break
    buffer += decoder.decode(chunk.value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const part of parts) {
      const line = part.split('\n').find((item) => item.startsWith('data:'))
      if (!line) continue
      const payload = JSON.parse(line.slice(5)) as { step: string }
      const current = figures.value.find((item) => item.figure_id === id)
      if (current && payload.step !== 'done') current.step = payload.step
      if (payload.step === 'done') {
        await refreshFigure(id)
        return
      }
    }
  }
  await refreshFigure(id)
}

async function refreshFigure(id: string) {
  const body = await api<FigureItem>(`/reports/figures/${id}`)
  const index = figures.value.findIndex((item) => item.figure_id === id)
  if (index < 0) figures.value.push(body)
  else figures.value[index] = body
  await attachPng(body)
}

async function attachPng(item: FigureItem) {
  if (item.echarts_option || !item.png_url || pngUrls.value[item.figure_id]) return
  const blob = await apiBlob(`/reports/figures/${item.figure_id}.png`)
  pngUrls.value[item.figure_id] = URL.createObjectURL(blob)
}

async function sendReply(item: FigureItem) {
  const text = (replyText.value[item.figure_id] || '').trim()
  const picks = replyPicks.value[item.figure_id] || []
  if ((!text && !picks.length) || figureBusy.value) return
  const savedStatus = item.status
  const savedQuestions = item.questions
  const savedNote = item.note
  const savedStep = item.step
  item.status = 'running'
  item.step = '正在根据补充计算'
  item.questions = []
  item.note = ''
  figureBusy.value = true
  figureError.value = ''
  try {
    await api(`/reports/figures/${item.figure_id}/reply`, {
      method: 'POST',
      body: JSON.stringify({ text, picks }),
    })
    replyText.value = { ...replyText.value, [item.figure_id]: '' }
    replyPicks.value = { ...replyPicks.value, [item.figure_id]: [] }
  } catch (err) {
    item.status = savedStatus
    item.questions = savedQuestions
    item.note = savedNote
    item.step = savedStep
    figureError.value = err instanceof Error ? err.message : '补充没有送出'
    return
  } finally {
    figureBusy.value = false
  }
  await followFigure(item.figure_id)
}

async function sendNext(item: FigureItem) {
  const text = (replyText.value[item.figure_id] || '').trim()
  if (!text || figureBusy.value) return
  replyText.value = { ...replyText.value, [item.figure_id]: '' }
  figurePrompt.value = text
  await createFigure()
}

function togglePick(id: string, option: string) {
  const current = replyPicks.value[id] || []
  const next = current.includes(option) ? current.filter((item) => item !== option) : [...current, option]
  replyPicks.value = { ...replyPicks.value, [id]: next }
}

function figureIsOpen(id: string, index: number) {
  if (id in figureOpen.value) return figureOpen.value[id]
  return index === 0
}

function toggleFigure(id: string, index: number) {
  figureOpen.value = { ...figureOpen.value, [id]: !figureIsOpen(id, index) }
}

function axisLabels(axis: any): string[] {
  const one = Array.isArray(axis) ? axis[0] : axis
  return Array.isArray(one?.data) ? one.data.map((item: unknown) => String(item)) : []
}

function inferredScope(option: any): string {
  const saved = option?.tip?.scope
  if (saved) return String(saved)
  const series = Array.isArray(option?.series) ? option.series : []
  if (series.some((item: any) => item?.type === 'heatmap')) return '分机台槽'
  const labels = [...axisLabels(option?.xAxis), ...axisLabels(option?.yAxis)]
  if (labels.some((label) => /M\d+/i.test(label) && /槽\d+/.test(label))) return '分机台槽'
  if (labels.some((label) => /^第\d+片$/.test(label))) return '整批'
  if (labels.some((label) => /^Temp_/i.test(label))) return '整批'
  const xName = String((Array.isArray(option?.xAxis) ? option.xAxis[0] : option?.xAxis)?.name || '')
  if (xName === '批次') return '分批次'
  if (xName === '机台') return '分机台'
  if (xName === '槽位') return '分机台槽'
  return ''
}

function withScope(title: string, scope: string) {
  if (!title) return scope
  if (!scope || title.includes(scope)) return title
  if (scope === '分机台槽' && title.includes('机台') && title.includes('槽')) return title
  return `${title} · ${scope}`
}

function figureTitle(item: FigureItem) {
  return withScope(item.title || item.prompt, inferredScope(item.panels?.[0]?.option || item.echarts_option))
}

function panelTitle(panel: FigurePanel) {
  return withScope(panel.title, inferredScope(panel.option))
}

function replyGuide(item: FigureItem) {
  if (item.note.includes('至少还要')) return item.note
  const questions = item.questions || []
  const asked = questions.map((question) => question.text.replace(/[？?]$/, '')).join('；')
  const blob = `${asked} ${item.note}`
  const allow = [
    ['图的类型', /类型|柱状|散点|箱线|折线|热力|纺锤|超限/],
    ['横轴', /横轴|横坐标/],
    ['纵轴', /纵轴|纵坐标/],
    ['均值、最小值、最大值、极差', /均值|最小值|最大值|极差/],
  ].filter(([, pattern]) => !pattern.test(blob)).map(([label]) => label)
  const need = asked || item.note || '画出这张图还缺的信息'
  return allow.length ? `至少还要：${need}。可以自己规定：${allow.join('、')}` : `至少还要：${need}`
}

function figureStatus(item: FigureItem) {
  if (item.status === 'asking') return '追问中'
  if (item.status === 'done') return '已出图'
  if (item.status === 'failed') return item.error || '出图失败'
  return item.step || '正在分析'
}

function dataTable(item: FigureItem): FigureTable | null {
  if (item.table?.columns.length) return item.table
  if (item.summary?.rows.length) return { name: `${item.prompt}所用数据`, columns: item.summary.columns, rows: item.summary.rows }
  return null
}

async function removeFigure(id: string) {
  await api(`/reports/figures/${id}`, { method: 'DELETE' })
  figures.value = figures.value.filter((item) => item.figure_id !== id)
}

const shots = new Map<string, { image: () => string }>()
function takeChart(id: string, el: unknown) {
  const chart = el as { image?: () => string } | null
  if (chart?.image) shots.set(id, chart as { image: () => string })
  else shots.delete(id)
}
function shot(id: string, title: string): { kind: 'image'; title: string; png: string } | { kind: 'text'; text: string } {
  const png = shots.get(id)?.image() || ''
  if (!png.startsWith('data:image/')) return { kind: 'text', text: `${title}：图没有截下来` }
  return { kind: 'image', title, png }
}
function pageBlocks() {
  const blocks: { kind: string; text?: string; title?: string; png?: string; columns?: string[]; rows?: string[][] }[] = []
  const add = (block: { kind: string; text?: string; title?: string; png?: string; columns?: string[]; rows?: string[][] } | null) => {
    if (block) blocks.push(block)
  }
  const heading = list.value.length === 1 ? list.value[0].batch_id : `${list.value.length} 个批次`
  blocks.push({ kind: 'h1', text: heading || '批次报告' })
  if (list.value.length) {
    blocks.push({
      kind: 'text',
      text: `${[...new Set(list.value.map((batch) => batch.model))].join(' / ')} · ${[...new Set(list.value.map((batch) => `${batch.plan_name || batch.plan_id} v${batch.plan_version}`))].join('，')}`,
    })
  }
  if (skipped.value.length) blocks.push({ kind: 'text', text: `这几个批次还没有测完的片子，没有放进分析：${skipped.value.join('、')}` })
  if (sum.value && list.value.length) {
    const current = sum.value
    const rc = hasRc.value ? `Rc 均值 ${current.rc_mean.toFixed(3)} ℃/W，σ ${current.rc_sd.toFixed(3)}` : 'Rc 均值 —'
    const cpk = current.cpk_t01 == null ? 'T0−T1 Cpk —' : `T0−T1 Cpk ${current.cpk_t01.toFixed(2)}`
    blocks.push({ kind: 'text', text: `测试数 ${current.tested} 片，中止 ${current.aborted}。良率 ${current.yield_rate.toFixed(2)}%。不合格 ${current.failed} 片。${rc}。${cpk}。机台 ${current.machine_count} 台。` })
  }
  blocks.push({ kind: 'h2', text: `AI 总结 · ${analysisTarget.value === 'product' ? '产品' : '机台'}` })
  for (const table of censusTables.value) {
    blocks.push({
      kind: 'table',
      title: '机台槽位片数和良率',
      columns: ['机台', '槽位', '片数', '良率'],
      rows: [
        [table.machines, '整批', String(table.tested), table.yield],
        ...table.slots.map((slot) => [slot.machine, slot.index, String(slot.tested), slot.yield]),
      ],
    })
  }
  if (limitFailOpt.value) {
    add(shot('limitFail', '超上限、超下限'))
    blocks.push({ kind: 'text', text: '柱子是这一项超上限的片数。柱子越高，超出去的片越多。' })
  }
  if (limitMeanOpt.value) {
    add(shot('limitMean', `同一项在${acrossLabel.value}的均值和上限下限`))
    blocks.push({ kind: 'text', text: '柱子是这一项的均值。红色虚线是上限，橙色虚线是下限。柱子高过红色虚线，均值就超了上限。' })
  }
  if (splitOpt.value) {
    add(shot('split', `同一项在${acrossLabel.value}的极差`))
    blocks.push({ kind: 'text', text: '柱底是最小值，柱顶是最大值，高度是极差。' })
  }
  else if (analysis.value && !analysis.value.note) blocks.push({ kind: 'text', text: analysisTarget.value === 'product' ? '现在只选了这一批。再选一批，才能把同一项按批次横向对比。' : '现在只有一个槽位，没有可横向对比的对象。' })
  if (analysis.value) {
    const current = analysis.value
    blocks.push({ kind: 'h2', text: '卡限项分析' })
    blocks.push({ kind: 'text', text: `有效 ${current.tested} 片 · 中止 ${current.aborted} · 未保留 ${current.discarded} · 无效读数 ${current.invalid}` })
    if (current.note) blocks.push({ kind: 'text', text: current.note })
    else if (current.overall.items.length && compareHeads.value.length > 1) {
      const heads = compareHeads.value
      blocks.push({ kind: 'text', text: heads.map((head) => `${head.label} ${head.name} · ${head.n} 片`).join('；') })
      blocks.push({
        kind: 'table',
        title: '卡限项',
        columns: ['项', '下限', '上限', ...heads.flatMap((head) => [`${head.label}片数`, `${head.label}均值`, `${head.label}极差`, `${head.label}超上限`, `${head.label}上限裕量`, `${head.label}时间顺序`])],
        rows: visibleItemNames.value.map((name) => [
          name,
          limitCell(name, 'low'),
          limitCell(name, 'high'),
          ...heads.flatMap((head) => {
            const item = sliceItem(head.slice, name)
            return [String(item?.n ?? 0), meas(name, item?.mean), meas(name, item?.range), String(item?.high_fail ?? 0), meas(name, item?.margin_high), item?.trend || '—']
          }),
        ]),
      })
    } else if (current.overall.items.length) {
      blocks.push({
        kind: 'table',
        title: '卡限项',
        columns: ['项', '下限', '上限', '片数', '均值', '最小值', '最大值', '极差', '重复性', '超上限', '超下限', '偏移', '上限裕量', '下限裕量', '时间顺序'],
        rows: visibleItemNames.value.map((name) => {
          const item = overallItem(name)
          return [
            name,
            limitCell(name, 'low'),
            limitCell(name, 'high'),
            String(item?.n ?? 0),
            meas(name, item?.mean),
            meas(name, item?.minimum),
            meas(name, item?.maximum),
            meas(name, item?.range),
            item?.retest_serials ? `${meas(name, item?.repeat_std)} 复测极差 ${meas(name, item?.retest_range)}` : meas(name, item?.repeat_std),
            String(item?.high_fail ?? 0),
            String(item?.low_fail ?? 0),
            item?.offset || '',
            meas(name, item?.margin_high),
            meas(name, item?.margin_low),
            item?.trend || '',
          ]
        }),
      })
    } else blocks.push({ kind: 'text', text: '方案里没有可分析的上下限' })
    if (compareHeads.value.length > 1) {
      const heads = compareHeads.value
      blocks.push({
        kind: 'table',
        title: `相关性 · 同一项在${acrossLabel.value}`,
        columns: ['项', ...heads.map((head) => head.label)],
        rows: visibleItemNames.value.map((name) => [
          name,
          ...heads.map((head) => {
            const item = sliceItem(head.slice, name)
            return `${meas(name, item?.mean)} · ${item?.n ?? 0} 片 · 超上限 ${item?.high_fail ?? 0} · 极差 ${meas(name, item?.range)}`
          }),
        ]),
      })
    }
    if (summaryLines.value.length) {
      blocks.push({ kind: 'h2', text: summaryMode.value === 'cross' ? '跨批次分析' : '单批次分析' })
      summaryLines.value.forEach((line) => blocks.push({ kind: 'text', text: line }))
      if (summaryLooked.value) blocks.push({ kind: 'text', text: summaryLooked.value })
    }
  }
  if (multi.value) add(shot('compare', '批次对比'))
  if (list.value.length) {
    if (report.value?.machine_yield.length) add(shot('yield', '分机台良率'))
    else blocks.push({ kind: 'text', text: '分机台良率：没有机台记录。' })
    if (t01Opt.value) add(shot('t01', 'Temp_T0-T1'))
    else blocks.push({ kind: 'text', text: '没有 Temp_T0-T1。' })
    if (paretoOpt.value) add(shot('pareto', '不合格项'))
    else blocks.push({ kind: 'text', text: '没有不合格项。' })
    if (profileOpt.value) add(shot('profile', '温差'))
    else blocks.push({ kind: 'text', text: '方案里没有卡限温差。' })
  }
  if (slotAmbientOpt.value) add(shot('ambient', '室温波动'))
  if (multi.value) {
    blocks.push({
      kind: 'table',
      title: '各批次',
      columns: ['批次号', '型号', '方案', '已测', '良率', 'Rc', '主要不合格项'],
      rows: list.value.map((batch) => [batch.batch_id, batch.model, `${batch.plan_name || batch.plan_id} v${batch.plan_version}`, String(batch.tested), batchYield(batch), batch.rc_mean ? batch.rc_mean.toFixed(3) : '—', batch.top_fail || '—']),
    })
  }
  if (figures.value.length) {
    blocks.push({ kind: 'h2', text: 'AI 补充分析' })
    for (const item of figures.value) {
      blocks.push({ kind: 'h2', text: figureTitle(item) })
      if (item.status === 'running') blocks.push({ kind: 'text', text: item.step || '正在分析' })
      if (item.error) blocks.push({ kind: 'text', text: item.error })
      if (item.panels?.length) item.panels.forEach((panel, index) => add(shot(`fig-${item.figure_id}-${index}`, panelTitle(panel) || figureTitle(item))))
      else if (item.echarts_option) add(shot(`fig-${item.figure_id}`, item.title || '补充分析'))
      const table = dataTable(item)
      if (table) blocks.push({ kind: 'table', title: table.name, columns: table.columns, rows: table.rows })
      if (item.summary) {
        blocks.push({ kind: 'text', text: item.summary.scope })
        item.summary.notes.forEach((note) => blocks.push({ kind: 'text', text: note }))
      } else if (!table) item.results.forEach((pair) => blocks.push({ kind: 'text', text: `${pair[0]}：${pair[1]}` }))
    }
  }
  return blocks.slice(0, 120)
}

function seriesType(panel: FigurePanel) {
  const series = panel.option?.series
  const first = Array.isArray(series) ? series[0] : null
  return String(first?.type || '')
}

function categoryCount(panel: FigurePanel) {
  const across = panel.option?.xAxis?.data
  const down = Array.isArray(panel.option?.yAxis) ? [] : panel.option?.yAxis?.data
  return Math.max(Array.isArray(across) ? across.length : 0, Array.isArray(down) ? down.length : 0)
}

function scatterCount(panel: FigurePanel) {
  const series = panel.option?.series
  if (!Array.isArray(series)) return 0
  return series.reduce((sum, item) => sum + (Array.isArray(item?.data) ? item.data.length : 0), 0)
}

function stackPanels(panels: FigurePanel[]) {
  if (panels.length !== 2) return true
  return panels.some((panel) => {
    const kind = seriesType(panel)
    if (kind === 'heatmap' || kind === 'boxplot' || kind === 'scatter' || kind === 'candlestick') return true
    return categoryCount(panel) > 4
  })
}

function panelHeight(panel: FigurePanel) {
  const kind = seriesType(panel)
  const count = categoryCount(panel)
  if (kind === 'heatmap') return Math.min(640, Math.max(120, 120 + count * 32))
  if (kind === 'scatter') return scatterCount(panel) > 200 ? 400 : 320
  if (count > 8) return Math.min(640, 160 + count * 28)
  if (count <= 6) return 260
  return Math.min(520, 260 + (count - 6) * 24)
}

function reportFileName() {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`
  const who = asked.value.length > 1 ? `${asked.value.length}批` : asked.value[0]
  return `批次报告_${who}_${stamp}.pdf`
}

async function exportPdf() {
  if (!asked.value.length) return
  try {
    const body = await api<{ url: string }>('/reports/export', {
      method: 'POST',
      body: JSON.stringify({
        batch_ids: asked.value,
        blocks: pageBlocks(),
        format: 'pdf',
      }),
    })
    const name = reportFileName()
    const link = document.createElement('a')
    link.href = body.url
    link.download = name
    link.click()
    app.toast({ kind: 'ok', title: '报告已导出', desc: name })
  } catch (err) {
    app.toast({ kind: 'danger', title: '导出失败', desc: err instanceof Error ? err.message : '报告没有导出' })
  }
}

function unitOf(name: string) {
  if (name === 'power_w' || name === '功率') return 'W'
  if (name.includes('Rc')) return '℃/W'
  if (name === '室温' || name.startsWith('Temp_') || name.startsWith('temp_')) return '℃'
  return ''
}

const machineYieldOpt = computed(() => {
  const t = tk.value
  const rows = report.value?.machine_yield ?? []
  const rates = rows.map((row) => +((row.passed / Math.max(1, row.n)) * 100).toFixed(2))
  return {
    grid: { left: 40, right: 12, top: 18, bottom: 24 },
    xAxis: { type: 'category', data: rows.map((row) => row.machine_id) },
    yAxis: { type: 'value', min: rates.length ? Math.min(90, Math.floor(Math.min(...rates) / 5) * 5) : 0, max: 100 },
    series: [{
      name: '良率', unit: '%', role: '良率', type: 'bar', barWidth: '50%',
      data: rates.map((value) => ({ value, itemStyle: { color: value < 97 ? t.danger : t.chart[0] } })),
      label: { show: true, position: 'top', fontSize: 10, color: t['text-2'], formatter: '{c}%' },
    }],
  }
})

const t01Opt = computed(() => {
  const t = tk.value
  const points = (report.value?.ambient ?? []).filter((point) => point.t01 != null).sort((a, b) => a.machine_id.localeCompare(b.machine_id) || a.slot_index - b.slot_index)
  if (!points.length) return null
  const grouped = new Map<string, number[]>()
  for (const point of points) {
    const name = `${point.machine_id} 槽${point.slot_index}`
    const rows = grouped.get(name) ?? []
    rows.push(point.t01 as number)
    grouped.set(name, rows)
  }
  const labels = [...grouped.keys()]
  const means = [...grouped.values()].map((rows) => +(rows.reduce((sum, value) => sum + value, 0) / rows.length).toFixed(2))
  const spec = analysis.value?.overall.items.find((item) => item.item === 'Temp_T0-T1')
  const limitText = (name: string, value: number | null | undefined) => value == null ? `${name} —` : `${name} ${value.toFixed(2)} ℃`
  return {
    grid: { left: 48, right: 16, top: 28, bottom: 36 },
    tooltip: {
      trigger: 'axis',
      formatter: (raw: unknown) => {
        const row = (Array.isArray(raw) ? raw[0] : raw) as { axisValue?: string; data?: { value?: number; n?: number }; marker?: string }
        return [
          row.axisValue ?? '',
          `${row.marker ?? ''}Temp_T0-T1 均值 ${row.data?.value ?? ''} ℃`,
          `${row.data?.n ?? 0} 片`,
          limitText('上限', spec?.high),
          limitText('下限', spec?.low),
        ].join('<br/>')
      },
    },
    xAxis: { type: 'category', data: labels, name: '机台槽位', nameLocation: 'middle', nameGap: 24 },
    yAxis: { type: 'value', name: '℃', scale: true },
    series: [{
      name: '均值',
      type: 'bar',
      barWidth: '46%',
      data: means.map((value, index) => ({ value, n: grouped.get(labels[index])?.length ?? 0 })),
      itemStyle: { color: t.chart[0] },
      label: { show: true, position: 'top', fontSize: 11, color: t['text-2'], formatter: (item: { value?: number }) => `${Number(item.value).toFixed(2)} ℃` },
    }],
  }
})

const slotAmbientOpt = computed(() => {
  const t = tk.value
  const points = (report.value?.ambient ?? []).filter((point) => point.value != null).sort((a, b) => a.machine_id.localeCompare(b.machine_id) || a.slot_index - b.slot_index || a.ended_at - b.ended_at)
  if (!points.length) return null
  const slotName = (point: { machine_id: string; slot_index: number }) => `${point.machine_id} 槽${point.slot_index}`
  const grouped = new Map<string, { value: number; serial: string }[]>()
  for (const point of points) {
    const name = slotName(point)
    const rows = grouped.get(name) ?? []
    rows.push({ value: point.value as number, serial: point.serial })
    grouped.set(name, rows)
  }
  const longest = Math.max(...[...grouped.values()].map((rows) => rows.length))
  const labels = Array.from({ length: longest }, (_, index) => `第${index + 1}片`)
  return {
    grid: { left: 52, right: 24, top: 36, bottom: 48 },
    legend: { type: 'scroll' },
    tooltip: {
      trigger: 'axis',
      formatter: (raw: unknown) => {
        const rows = (Array.isArray(raw) ? raw : [raw]) as { marker?: string; seriesName?: string; value?: number | null; data?: { serial?: string }; axisValue?: string }[]
        const visible = rows.filter((row) => row.value != null)
        if (!visible.length) return ''
        const body = visible.map((row) => `${row.marker ?? ''}${row.seriesName ?? ''} ${row.data?.serial ?? ''} 室温 单片 ${Number(row.value).toFixed(2)} ℃`)
        return [visible[0].axisValue ?? '', ...body].join('<br/>')
      },
    },
    xAxis: {
      type: 'category',
      data: labels,
      name: '槽位内测试先后',
      nameLocation: 'middle',
      nameGap: 28,
      axisLabel: { interval: longest > 16 ? Math.ceil(longest / 16) - 1 : 0 },
    },
    yAxis: { type: 'value', name: '℃', scale: true },
    series: [...grouped.entries()].map(([name, rows], seriesIndex) => ({
      name,
      type: 'line',
      showSymbol: true,
      symbolSize: 10,
      data: labels.map((_, order) => (rows[order] ? { value: rows[order].value, serial: rows[order].serial } : null)),
      itemStyle: { color: t.chart[seriesIndex % 6] },
    })),
  }
})

const paretoOpt = computed(() => {
  const t = tk.value
  const rows = report.value?.fail_pareto ?? []
  if (!rows.length) return null
  const tested = report.value?.summary.tested ?? 0
  const rate = rows.map((row) => (tested > 0 ? +((row.count / tested) * 100).toFixed(1) : 0))
  return {
    grid: { left: 36, right: 40, top: 26, bottom: 44 },
    legend: { data: ['不合格片数', '占本批'] },
    xAxis: { type: 'category', data: rows.map((row) => row.item), axisLabel: { interval: 0, rotate: 20 } },
    yAxis: [{ type: 'value', name: '片' }, { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } }],
    series: [
      { name: '不合格片数', unit: '片', role: '片数', type: 'bar', data: rows.map((row) => row.count), itemStyle: { color: t.danger } },
      { name: '占本批', unit: '%', role: '占比', type: 'line', yAxisIndex: 1, data: rate, itemStyle: { color: t.chart[1] } },
    ],
  }
})

const profileOpt = computed(() => {
  const t = tk.value
  const profile = report.value?.delta_profile
  if (!profile?.items.length) return null
  const series = list.value.map((batch, index) => ({
    name: batch.batch_id, unit: '℃', role: '均值', type: 'line', connectNulls: false, data: profile.mean[batch.batch_id] ?? [], itemStyle: { color: t.chart[index % 6] },
  }))
  if (profile.p95) series.push({ name: 'P95', unit: '℃', role: 'P95', type: 'line', connectNulls: false, data: profile.p95, itemStyle: { color: t.warn } })
  if (profile.limit.some((value) => value != null)) {
    series.push({
      name: '上限', unit: '℃', role: '上限', type: 'line', connectNulls: false, showSymbol: true, symbol: 'circle', symbolSize: 6,
      data: profile.limit, lineStyle: { type: 'dashed', color: t.danger }, itemStyle: { color: t.danger },
    })
  }
  return {
    grid: { left: 40, right: 12, top: 30, bottom: 52 },
    legend: { type: 'scroll' },
    xAxis: { type: 'category', data: profile.items, axisLabel: { interval: 0, rotate: 28 } },
    yAxis: { type: 'value', name: '℃', min: 0 },
    series,
  }
})

const limitFailOpt = computed(() => {
  const items = analysis.value?.overall.items ?? []
  const names = orderedItemNames.value
  const heads = compareHeads.value
  const t = tk.value
  if (heads.length > 1 && names.length) {
    return {
      tooltip: { formatter: (params: { axisValue?: string; name?: string } | { axisValue?: string; name?: string }[]) => detailTip(String((Array.isArray(params) ? params[0] : params)?.axisValue || (Array.isArray(params) ? params[0] : params)?.name || '')) },
      grid: { left: 36, right: 16, top: 36, bottom: 8, containLabel: true },
      legend: { type: 'scroll', data: heads.map((head) => head.label) },
      xAxis: { type: 'category', data: names, axisLabel: { interval: 0, rotate: 40 } },
      yAxis: { type: 'value', minInterval: 1 },
      series: heads.map((head) => ({
        name: head.label, unit: '片', role: '超上限', type: 'bar',
        data: names.map((name) => sliceItem(head.slice, name)?.high_fail ?? 0),
        itemStyle: { color: head.color },
      })),
    }
  }
  if (!items.length) return null
  return {
    grid: { left: 36, right: 12, top: 28, bottom: 48 },
    legend: { data: ['超上限', '超下限'] },
    xAxis: { type: 'category', data: items.map((item) => item.item), axisLabel: { interval: 0, rotate: 18 } },
    yAxis: { type: 'value', name: '片', minInterval: 1 },
    series: [
      { name: '超上限', unit: '片', role: '片数', type: 'bar', data: items.map((item) => item.high_fail), itemStyle: { color: t.danger } },
      { name: '超下限', unit: '片', role: '片数', type: 'bar', data: items.map((item) => item.low_fail), itemStyle: { color: t.chart[1] } },
    ],
  }
})

const limitMeanOpt = computed(() => {
  const items = analysis.value?.overall.items ?? []
  const names = scaledNames(orderedItemNames.value)
  const heads = compareHeads.value
  const t = tk.value
  if (heads.length > 1 && names.length) {
    return {
      tooltip: { formatter: (params: { axisValue?: string; name?: string } | { axisValue?: string; name?: string }[]) => detailTip(String((Array.isArray(params) ? params[0] : params)?.axisValue || (Array.isArray(params) ? params[0] : params)?.name || '')) },
      grid: { left: 44, right: 16, top: 36, bottom: 8, containLabel: true },
      legend: { type: 'scroll', data: heads.map((head) => head.label) },
      xAxis: { type: 'category', data: names, axisLabel: { interval: 0, rotate: 40 } },
      yAxis: { type: 'value' },
      series: [
        ...heads.map((head) => ({
          name: head.label, role: '均值', type: 'bar',
          data: names.map((name) => ({ value: sliceItem(head.slice, name)?.mean ?? null, unit: unitOf(name) })),
          itemStyle: { color: head.color },
        })),
        { name: '上限', role: '上限', type: 'line', data: names.map((name) => ({ value: sliceItem(heads[0].slice, name)?.high ?? analysis.value?.overall.items.find((item) => item.item === name)?.high ?? null, unit: unitOf(name) })), symbol: 'none', lineStyle: { type: 'dashed' }, itemStyle: { color: t.danger } },
        { name: '下限', role: '下限', type: 'line', data: names.map((name) => ({ value: sliceItem(heads[0].slice, name)?.low ?? analysis.value?.overall.items.find((item) => item.item === name)?.low ?? null, unit: unitOf(name) })), symbol: 'none', lineStyle: { type: 'dashed' }, itemStyle: { color: t.warn } },
      ],
    }
  }
  if (!items.length) return null
  return {
    grid: { left: 44, right: 12, top: 28, bottom: 48 },
    legend: { data: ['均值', '最大值', '最小值', '上限', '下限'] },
    xAxis: { type: 'category', data: items.map((item) => item.item), axisLabel: { interval: 0, rotate: 18 } },
    yAxis: { type: 'value' },
    series: [
      { name: '均值', role: '均值', type: 'bar', data: items.map((item) => ({ value: item.mean, unit: unitOf(item.item) })), itemStyle: { color: t.chart[0] } },
      { name: '最大值', role: '最大值', type: 'line', data: items.map((item) => ({ value: item.maximum, unit: unitOf(item.item) })), symbol: 'triangle', symbolSize: 9, itemStyle: { color: t.chart[2] } },
      { name: '最小值', role: '最小值', type: 'line', data: items.map((item) => ({ value: item.minimum, unit: unitOf(item.item) })), symbol: 'diamond', symbolSize: 8, itemStyle: { color: t.chart[4] } },
      { name: '上限', role: '上限', type: 'line', data: items.map((item) => ({ value: item.high, unit: unitOf(item.item) })), symbol: 'none', itemStyle: { color: t.danger } },
      { name: '下限', role: '下限', type: 'line', data: items.map((item) => ({ value: item.low, unit: unitOf(item.item) })), symbol: 'none', itemStyle: { color: t.warn } },
    ],
  }
})

const splitOpt = computed(() => {
  const data = analysis.value
  const heads = compareHeads.value
  if (!data || data.note || !heads.length) return null
  const names = scaledNames(orderedItemNames.value)
  if (!names.length) return null
  let axisMin = 0
  for (const head of heads) {
    for (const name of names) {
      const low = sliceItem(head.slice, name)?.minimum
      if (low != null && low < axisMin) axisMin = low
    }
  }
  return {
    grid: { left: 44, right: 16, top: 36, bottom: 8, containLabel: true },
    legend: { type: 'scroll', data: heads.map((head) => ({ name: head.label, itemStyle: { color: head.color } })) },
    tooltip: {
      formatter: (params: { axisValue?: string; seriesName?: string; data?: { value?: number | null; minimum?: number | null; maximum?: number | null } }[]) => {
        const rows = Array.isArray(params) ? params : [params]
        const itemName = String(rows[0]?.axisValue || '')
        const lines = [itemName]
        const seen = new Set<string>()
        for (const row of rows) {
          const point = row.data
          const label = String(row.seriesName || '')
          if (!point || point.maximum == null || seen.has(label)) continue
          seen.add(label)
          lines.push(`${label} 最小 ${meas(itemName, point.minimum)} 最大 ${meas(itemName, point.maximum)} 极差 ${meas(itemName, point.value)}`)
        }
        return lines.join('<br/>')
      },
    },
    xAxis: { type: 'category', data: names, axisLabel: { interval: 0, rotate: 40 } },
    yAxis: { type: 'value', min: axisMin },
    series: heads.flatMap((head) => {
      const points = names.map((name) => {
        const item = sliceItem(head.slice, name)
        if (item?.minimum == null || item.maximum == null) return null
        const span = item.range ?? item.maximum - item.minimum
        return { base: item.minimum, value: span, minimum: item.minimum, maximum: item.maximum, unit: unitOf(name) }
      })
      return [
        {
          name: head.label, type: 'bar', stack: head.label, silent: true,
          data: points.map((point) => (point ? { value: point.base, unit: point.unit, spanBase: true } : null)),
          itemStyle: { color: 'transparent' },
          emphasis: { disabled: true },
        },
        {
          name: head.label, role: '极差', type: 'bar', stack: head.label,
          data: points.map((point) => (point ? { value: point.value, minimum: point.minimum, maximum: point.maximum, unit: point.unit } : null)),
          itemStyle: { color: head.color },
        },
      ]
    }),
  }
})

const compareOpt = computed(() => {
  const t = tk.value
  const rows = report.value?.compare ?? []
  return {
    grid: { left: 40, right: 46, top: 28, bottom: 24 },
    legend: {},
    xAxis: { type: 'category', data: rows.map((row) => row.batch_id) },
    yAxis: [{ type: 'value', name: '良率 %', min: 0, max: 100 }, { type: 'value', name: 'Rc', scale: true }],
    series: [
      { name: '良率', unit: '%', role: '良率', type: 'bar', data: rows.map((row) => row.yield_rate), itemStyle: { color: t.chart[0] } },
      { name: 'Rc 均值', unit: '℃/W', role: '均值', type: 'line', yAxisIndex: 1, data: rows.map((row) => row.rc_mean || null), itemStyle: { color: t.chart[2] } },
    ],
  }
})
</script>

<template>
  <div class="page report">
    <header class="rh">
      <button class="btn btn-ghost btn-icon" v-tip="'返回测试执行'" @click="router.push({ path: '/testing', query: { tab: 'history' } })"><ArrowLeft :size="18" /></button>
      <div class="grow" style="min-width: 0">
        <div class="row">
          <span class="code-label">{{ multi ? `COMBINED · ${list.length}` : 'BATCH REPORT' }}</span>
          <StatusTag v-if="list.length === 1" :status="list[0].state === 'running' ? 'RUNNING' : list[0].state" :text="list[0].state === 'running' ? '进行中' : undefined" />
        </div>
        <h1>{{ list.length === 1 ? list[0].batch_id : multi ? `${list.length} 个批次` : '批次报告' }}</h1>
        <p v-if="list.length" class="fs-sm muted">
          {{ [...new Set(list.map((b) => b.model))].join(' / ') }} ·
          {{ [...new Set(list.map((b) => `${b.plan_name || b.plan_id} v${b.plan_version}`))].join('，') }} ·
          {{ dt(Math.min(...list.map((b) => b.started_at))) }} 起
        </p>
      </div>
      <button class="btn btn-primary" :disabled="!asked.length || !!error" @click="exportPdf"><Download :size="16" />导出 PDF</button>
    </header>

    <p v-if="loading" class="muted">正在汇总测试结果…</p>
    <p v-else-if="error" class="t-danger">{{ error }}</p>
    <template v-else-if="sum">
      <p v-if="!list.length" class="muted">所选批次还没有测完的片子，先不出结果。</p>
      <p v-else-if="skipped.length" class="fs-sm muted">这几个批次还没有测完的片子，没有放进分析：{{ skipped.join('、') }}</p>

      <div v-if="list.length" class="grid g-6">
        <Kpi label="测试数" :value="sum.tested" unit="片" :sub="`中止 ${sum.aborted}`" />
        <Kpi label="良率" :value="sum.yield_rate.toFixed(2)" unit="%" :state="sum.yield_rate >= 97 ? 'ok' : 'warn'" />
        <Kpi label="不合格" :value="sum.failed" unit="片" :state="sum.failed ? 'warn' : 'ok'" />
        <Kpi label="Rc 均值" :value="hasRc ? sum.rc_mean.toFixed(3) : '—'" unit="℃/W" :sub="hasRc ? `σ ${sum.rc_sd.toFixed(3)}` : '没有测量值'" />
        <Kpi label="T0−T1 Cpk" :value="sum.cpk_t01 == null ? '—' : sum.cpk_t01.toFixed(2)" :state="sum.cpk_t01 == null ? undefined : sum.cpk_t01 >= 1.33 ? 'ok' : sum.cpk_t01 >= 1 ? 'warn' : 'danger'" :sub="sum.usl_t01 == null ? '方案没有这项上限' : `上限 ${sum.usl_t01} ℃`" />
        <Kpi label="机台" :value="sum.machine_count" unit="台" />
      </div>

      <Panel v-if="list.length" title="AI 总结" code="8.2" :icon="Sparkles">
        <div class="row batch-switch">
          <div class="seg">
            <button type="button" :aria-pressed="analysisTarget === 'product'" @click="analysisTarget = 'product'">产品</button>
            <button type="button" :aria-pressed="analysisTarget === 'machine'" @click="analysisTarget = 'machine'">机台</button>
          </div>
          <p v-if="compareHeads.length" class="batch-key">
            <span v-for="head in compareHeads" :key="head.name" class="legend-bit"><i :style="{ background: head.color }"></i>{{ head.label }} {{ head.name }} · {{ head.n < 30 ? '不足片' : `${head.n} 片` }}</span>
          </p>
        </div>
        <button v-if="censusTables.length" type="button" class="btn btn-sm census-toggle" :class="{ 'btn-primary': censusOpen }" :aria-expanded="censusOpen" @click="censusOpen = !censusOpen">{{ censusOpen ? '收起' : '展开' }}机台槽位片数和良率</button>
        <template v-if="censusOpen">
        <div v-for="table in censusTables" :key="table.batch" class="table-wrap census-table">
          <table class="table">
            <thead>
              <tr><th>机台</th><th>槽位</th><th class="r">片数</th><th class="r">良率</th></tr>
            </thead>
            <tbody>
              <tr>
                <td>{{ table.machines }}</td>
                <td>整批</td>
                <td class="r num">{{ table.tested }}</td>
                <td class="r num">{{ table.yield }}</td>
              </tr>
              <tr v-for="slot in table.slots" :key="slot.slot">
                <td>{{ slot.machine }}</td>
                <td class="mono">{{ slot.index }}</td>
                <td class="r num">{{ slot.tested }}</td>
                <td class="r num">{{ slot.yield }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        </template>
        <div v-if="limitFailOpt || limitMeanOpt" class="grid g-2 chart-row">
          <div v-if="limitFailOpt">
            <p class="fs-sm fw-6">超上限、超下限</p>
            <p class="fs-xs muted">柱子是这一项超上限的片数。柱子越高，超出去的片越多。</p>
            <EChart :ref="(el) => takeChart('limitFail', el)" :option="limitFailOpt" :height="280" />
          </div>
          <div v-if="limitMeanOpt">
            <p class="fs-sm fw-6">同一项在{{ acrossLabel }}的均值和上限下限</p>
            <p class="fs-xs muted">柱子是这一项的均值。红色虚线是上限，橙色虚线是下限。柱子高过红色虚线，均值就超了上限。</p>
            <EChart :ref="(el) => takeChart('limitMean', el)" :option="limitMeanOpt" :height="280" />
          </div>
        </div>
        <div v-if="splitOpt" class="chart-row">
          <p class="fs-sm fw-6">同一项在{{ acrossLabel }}的极差</p>
          <p class="fs-xs muted">柱底是最小值，柱顶是最大值，高度是极差。</p>
          <EChart :ref="(el) => takeChart('split', el)" :option="splitOpt" :height="300" />
        </div>
      </Panel>

      <Panel v-if="analysis" title="卡限项分析" code="LIMITS" :icon="BarChart3">
        <p class="fs-xs muted">有效 {{ analysis.tested }} 片 · 中止 {{ analysis.aborted }} · 未保留 {{ analysis.discarded }} · 无效读数 {{ analysis.invalid }}</p>
        <p v-if="analysis.note" class="muted">{{ analysis.note }}</p>
        <div v-else>
          <div class="legend-block">
            <p class="fs-sm legend-row">
              <span v-for="head in compareHeads" :key="head.name" class="legend-bit"><i :style="{ background: head.color }"></i>{{ head.label }} {{ head.name }} · {{ head.n < 30 ? '不足片' : `${head.n} 片` }}</span>
            </p>
            <button v-if="hiddenCount" type="button" class="btn btn-sm" :class="{ 'btn-primary': showQuiet }" @click="showQuiet = !showQuiet">{{ showQuiet ? '收起持平项' : `展开其余 ${hiddenCount} 项，限内且持平` }}</button>
            <p class="fs-xs legend-note"><span class="t-danger">红字</span> 超限片数大于 0 · <span class="cell-warn">浅黄底</span> 上限裕量小于 0.3℃，或两批都不是不足片且极差差到 2 倍 · <span class="muted">灰字</span> 不足片</p>
          </div>
          <div class="table-wrap">
          <table class="table">
            <thead>
              <tr v-if="compareHeads.length > 1">
                <th>项</th>
                <th class="r">下限</th>
                <th class="r">上限</th>
                <template v-for="head in compareHeads" :key="head.label">
                  <th class="r">{{ head.label }}片数</th>
                  <th class="r">{{ head.label }}均值</th>
                  <th class="r">{{ head.label }}极差</th>
                  <th class="r">{{ head.label }}超上限</th>
                  <th class="r">{{ head.label }}上限裕量</th>
                  <th>{{ head.label }}时间顺序</th>
                </template>
              </tr>
              <tr v-else><th>项</th><th class="r">下限</th><th class="r">上限</th><th class="r">片数</th><th class="r">均值</th><th class="r">最小值</th><th class="r">最大值</th><th class="r">极差</th><th class="r">重复性</th><th class="r">超上限</th><th class="r">超下限</th><th>偏移</th><th class="r">上限裕量</th><th class="r">下限裕量</th><th>时间顺序</th></tr>
            </thead>
            <tbody>
              <tr v-for="name in visibleItemNames" :key="name">
                <td class="mono fs-xs">{{ name }}</td>
                <td class="r num">{{ limitCell(name, 'low') }}</td>
                <td class="r num">{{ limitCell(name, 'high') }}</td>
                <template v-if="compareHeads.length > 1">
                  <template v-for="head in compareHeads" :key="head.label">
                    <td class="r num" :class="countClass(sliceItem(head.slice, name)?.n)">{{ sliceItem(head.slice, name)?.n ?? 0 }}</td>
                    <td class="r num">{{ meas(name, sliceItem(head.slice, name)?.mean) }}</td>
                    <td class="r num" :class="rangeClass(name, sliceItem(head.slice, name))">{{ meas(name, sliceItem(head.slice, name)?.range) }}</td>
                    <td class="r num" :class="failClass(sliceItem(head.slice, name)?.high_fail)">{{ sliceItem(head.slice, name)?.high_fail ?? 0 }}</td>
                    <td class="r num" :class="marginClass(sliceItem(head.slice, name)?.margin_high)">{{ meas(name, sliceItem(head.slice, name)?.margin_high) }}</td>
                    <td>{{ sliceItem(head.slice, name)?.trend || '—' }}</td>
                  </template>
                </template>
                <template v-else>
                  <td class="r num" :class="countClass(overallItem(name)?.n)">{{ overallItem(name)?.n ?? 0 }}</td>
                  <td class="r num">{{ meas(name, overallItem(name)?.mean) }}</td>
                  <td class="r num">{{ meas(name, overallItem(name)?.minimum) }}</td>
                  <td class="r num">{{ meas(name, overallItem(name)?.maximum) }}</td>
                  <td class="r num">{{ meas(name, overallItem(name)?.range) }}</td>
                  <td class="r num">{{ meas(name, overallItem(name)?.repeat_std) }}<span v-if="overallItem(name)?.retest_serials" class="fs-xs muted"> 复测极差 {{ meas(name, overallItem(name)?.retest_range) }}</span></td>
                  <td class="r num" :class="failClass(overallItem(name)?.high_fail)">{{ overallItem(name)?.high_fail ?? 0 }}</td>
                  <td class="r num" :class="failClass(overallItem(name)?.low_fail)">{{ overallItem(name)?.low_fail ?? 0 }}</td>
                  <td>{{ overallItem(name)?.offset }}</td>
                  <td class="r num" :class="marginClass(overallItem(name)?.margin_high)">{{ meas(name, overallItem(name)?.margin_high) }}</td>
                  <td class="r num">{{ meas(name, overallItem(name)?.margin_low) }}</td>
                  <td>{{ overallItem(name)?.trend }}</td>
                </template>
              </tr>
              <tr v-if="!analysis.overall.items.length"><td :colspan="compareHeads.length > 1 ? 3 + compareHeads.length * 6 : 15" class="c muted">方案里没有可分析的上下限</td></tr>
            </tbody>
          </table>
          </div>
        </div>
        <div v-if="compareHeads.length > 1" class="batch-sum">
          <div class="row-between">
            <p class="fs-sm fw-6">相关性 · 同一项在{{ acrossLabel }}</p>
            <button v-if="hiddenCount" type="button" class="btn btn-sm" :class="{ 'btn-primary': showQuiet }" @click="showQuiet = !showQuiet">{{ showQuiet ? '收起持平项' : `展开其余 ${hiddenCount} 项，限内且持平` }}</button>
          </div>
          <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>项</th>
                <th v-for="head in compareHeads" :key="head.label">{{ head.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="name in visibleItemNames" :key="name">
                <td class="mono fs-xs">{{ name }}</td>
                <td v-for="head in compareHeads" :key="head.label" :class="failClass(sliceItem(head.slice, name)?.high_fail)">
                  {{ meas(name, sliceItem(head.slice, name)?.mean) }} · {{ sliceItem(head.slice, name)?.n ?? 0 }} 片 · 超上限 {{ sliceItem(head.slice, name)?.high_fail ?? 0 }} · 极差 {{ meas(name, sliceItem(head.slice, name)?.range) }}
                </td>
              </tr>
            </tbody>
          </table>
          </div>
        </div>
      </Panel>

      <Panel v-if="list.length" title="结果" code="ANALYSIS">
        <div class="row">
          <button type="button" class="btn btn-sm" :class="{ 'btn-primary': summaryMode === 'single' }" :disabled="summaryBusy" @click="loadSummary('single')">{{ summaryBusy && summaryMode === 'single' ? '正在分析…' : '单批次分析' }}</button>
          <button type="button" class="btn btn-sm" :class="{ 'btn-primary': summaryMode === 'cross' }" :disabled="summaryBusy || list.length < 2" @click="loadSummary('cross')">{{ summaryBusy && summaryMode === 'cross' ? '正在分析…' : '跨批次分析' }}</button>
          <button v-if="summaryLines.length" type="button" class="btn btn-sm" :class="{ 'btn-primary': summaryOpen }" :aria-expanded="summaryOpen" @click="summaryOpen = !summaryOpen">{{ summaryOpen ? '收起' : '展开' }}</button>
        </div>
        <p v-if="list.length < 2" class="fs-xs muted">只导入了一批，跨批次分析不可用。</p>
        <p v-if="summaryError" class="t-danger">{{ summaryError }}</p>
        <div v-else-if="summaryLines.length && summaryOpen" class="sum-text">
          <p v-for="(line, index) in summaryLines" :key="index" :class="{ 'fw-6': summaryLead(line) === line, 'sum-gap': summaryBreak(line, index), 'sum-batch': index > 0 && line === '已暴露的卡限项' }">
            <template v-if="summaryLead(line) && summaryLead(line) !== line"><span class="fw-6">{{ summaryLead(line) }}</span>{{ line.slice(summaryLead(line).length) }}</template>
            <template v-else>{{ line }}</template>
          </p>
          <p v-if="summaryLooked" class="fs-xs muted">{{ summaryLooked }}</p>
        </div>
        <p v-else-if="!summaryLines.length" class="muted">选一种分析。结论分成已暴露的卡限项和潜在危险项。多批时点单批次分析，会按一批一段分开写。</p>
        <p v-if="summaryModel" class="fs-xs muted">{{ summaryModel }}</p>
      </Panel>

      <Panel v-if="multi" title="批次对比" code="YIELD · RC" :icon="BarChart3">
        <EChart :ref="(el) => takeChart('compare', el)" :option="compareOpt" :height="240" />
      </Panel>

      <div v-if="list.length" class="grid g-2">
        <Panel title="分机台良率" code="BY MACHINE" :icon="BarChart3">
          <EChart v-if="report?.machine_yield.length" :ref="(el) => takeChart('yield', el)" :option="machineYieldOpt" :height="240" />
          <p v-else class="muted">没有机台记录。</p>
        </Panel>
        <Panel title="Temp_T0-T1" code="槽位均值" :icon="BarChart3">
          <EChart v-if="t01Opt" :ref="(el) => takeChart('t01', el)" :option="t01Opt" :height="240" />
          <p v-else class="muted">没有 Temp_T0-T1。</p>
        </Panel>
        <Panel title="不合格项" code="FAIL ITEMS" :icon="BarChart3">
          <EChart v-if="paretoOpt" :ref="(el) => takeChart('pareto', el)" :option="paretoOpt" :height="240" />
          <p v-else class="muted">没有不合格项。</p>
        </Panel>
        <Panel title="温差" code="卡限 ΔT" :icon="BarChart3">
          <EChart v-if="profileOpt" :ref="(el) => takeChart('profile', el)" :option="profileOpt" :height="240" />
          <p v-else class="muted">方案里没有卡限温差。</p>
        </Panel>
      </div>

      <Panel v-if="slotAmbientOpt" title="室温波动" code="各槽位一条线" :icon="BarChart3">
        <EChart :ref="(el) => takeChart('ambient', el)" :option="slotAmbientOpt" :height="340" />
      </Panel>

      <Panel v-if="multi" title="各批次" code="BATCHES" flush>
        <div class="table-wrap" style="border-top: 0">
          <table class="table">
            <thead><tr><th>批次号</th><th>型号</th><th>方案</th><th class="r">已测</th><th class="r">良率</th><th class="r">Rc</th><th>主要不合格项</th></tr></thead>
            <tbody>
              <tr v-for="batch in list" :key="batch.batch_id">
                <td class="mono fs-sm fw-6">{{ batch.batch_id }}</td>
                <td>{{ batch.model }}</td>
                <td class="fs-sm">{{ batch.plan_name || batch.plan_id }} v{{ batch.plan_version }}</td>
                <td class="r num">{{ batch.tested }}</td>
                <td class="r num">{{ batchYield(batch) }}</td>
                <td class="r num">{{ batch.rc_mean ? batch.rc_mean.toFixed(3) : '—' }}</td>
                <td class="mono fs-xs">{{ batch.top_fail || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel v-if="list.length" title="Agent 补充分析" code="8.3" :icon="Bot">
        <div class="preset-row">
          <button v-for="item in figurePresets" :key="item.id" type="button" class="btn btn-sm" :disabled="figureBusy" @click="createFigure(item.id)">{{ item.label }}</button>
        </div>
        <div class="row">
          <input v-model="figurePrompt" class="input grow" placeholder="或者写一句，例如：按机台比较 Temp_T0-T1" :disabled="figureBusy" @keydown.enter="createFigure()" />
          <button type="button" class="btn btn-sm" :disabled="figureBusy || !figurePrompt.trim()" @click="createFigure()">{{ figureBusy ? '正在分析…' : '生成' }}</button>
        </div>
        <p v-if="figureError" class="t-danger">{{ figureError }}</p>
        <p v-else-if="!figures.length" class="muted">点一个分析，或写一句要求。图会用这些批次的测试记录算出来，加在这份报告上。</p>
        <article v-for="(item, index) in figures" :key="item.figure_id" class="figure">
          <div class="row-between">
            <button type="button" class="btn btn-sm" :class="{ 'btn-primary': figureIsOpen(item.figure_id, index) }" :aria-expanded="figureIsOpen(item.figure_id, index)" @click="toggleFigure(item.figure_id, index)">{{ figureIsOpen(item.figure_id, index) ? '收起' : '展开' }}</button>
            <b>{{ figureTitle(item) }}</b>
            <span class="fs-sm muted figure-status"><Loader2 v-if="item.status === 'running'" :size="14" class="spin" />{{ figureStatus(item) }}</span>
            <button type="button" class="btn btn-ghost btn-sm" @click="removeFigure(item.figure_id)">移除</button>
          </div>
          <div v-show="figureIsOpen(item.figure_id, index)">
            <p v-if="item.status === 'running'" class="fs-sm muted figure-status"><Loader2 :size="14" class="spin" />{{ item.step || '正在分析' }}</p>
            <p v-else-if="item.error" class="t-danger">{{ item.error }}</p>
            <div v-if="item.status === 'asking'" class="ask">
              <p v-if="item.note" class="fs-sm">{{ item.note }}</p>
              <section v-for="(question, questionIndex) in item.questions || []" :key="questionIndex">
                <p class="fs-sm">{{ question.text }}</p>
                <div class="preset-row">
                  <button v-for="option in question.options" :key="option" type="button" class="btn btn-sm" :class="{ 'btn-primary': (replyPicks[item.figure_id] || []).includes(option) }" @click="togglePick(item.figure_id, option)">{{ option }}</button>
                </div>
              </section>
              <div class="row">
                <input v-model="replyText[item.figure_id]" class="input grow" :placeholder="replyGuide(item)" :title="replyGuide(item)" :disabled="figureBusy" @keydown.enter="sendReply(item)" />
                <button type="button" class="btn btn-sm" :disabled="figureBusy" @click="sendReply(item)">发送</button>
              </div>
              <p class="fs-sm muted">{{ replyGuide(item) }}</p>
            </div>
            <div v-else-if="item.status === 'done'" class="ask">
              <div class="row">
                <input v-model="replyText[item.figure_id]" class="input grow" placeholder="在这张图的基础上再出一张" :disabled="figureBusy" @keydown.enter="sendNext(item)" />
                <button type="button" class="btn btn-sm" :disabled="figureBusy || !(replyText[item.figure_id] || '').trim()" @click="sendNext(item)">发送</button>
              </div>
            </div>
            <div v-if="item.panels?.length" class="figure-grid" :class="{ stack: stackPanels(item.panels) }">
              <section v-for="(panel, panelIndex) in item.panels" :key="panelIndex">
                <p v-if="panelTitle(panel)" class="fs-sm muted">{{ panelTitle(panel) }}</p>
                <EChart :ref="(el) => takeChart(`fig-${item.figure_id}-${panelIndex}`, el)" :option="panel.option" :height="panelHeight(panel)" />
              </section>
            </div>
            <EChart v-else-if="item.echarts_option" :ref="(el) => takeChart(`fig-${item.figure_id}`, el)" :option="item.echarts_option" :height="panelHeight({ title: '', option: item.echarts_option })" />
            <img v-else-if="pngUrls[item.figure_id]" :src="pngUrls[item.figure_id]" alt="" class="png" />
            <p v-if="item.summary" class="fs-sm">{{ item.summary.scope }}</p>
            <template v-if="dataTable(item)">
              <button type="button" class="btn btn-sm" :class="{ 'btn-primary': tableOpen[item.figure_id] }" :aria-expanded="!!tableOpen[item.figure_id]" @click="tableOpen[item.figure_id] = !tableOpen[item.figure_id]">{{ tableOpen[item.figure_id] ? '收起' : '展开' }}{{ dataTable(item)?.name }}</button>
              <div v-if="tableOpen[item.figure_id]" class="table-wrap">
                <table class="table">
                  <thead>
                    <tr><th v-for="column in dataTable(item)?.columns" :key="column">{{ column }}</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rowIndex) in dataTable(item)?.rows" :key="rowIndex">
                      <td v-for="(cell, cellIndex) in row" :key="cellIndex" :class="cellIndex ? 'r num' : 'mono fs-xs'">{{ cell }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
            <p v-for="note in item.summary?.notes || []" :key="note" class="fs-sm muted">{{ note }}</p>
            <table v-if="!dataTable(item) && item.results.length" class="table">
              <tbody>
                <tr v-for="(pair, pairIndex) in item.results" :key="pairIndex"><td>{{ pair[0] }}</td><td class="num">{{ pair[1] }}</td></tr>
              </tbody>
            </table>
          </div>
        </article>
      </Panel>
    </template>
  </div>
</template>

<style scoped>
.sum-text p { margin: 0 0 6px; line-height: 1.7; }
.sum-text .sum-gap { margin-top: 14px; }
.sum-text .sum-batch { margin-top: 28px; padding-top: 16px; border-top: var(--bw) solid var(--c-border); }
.batch-switch { flex-wrap: wrap; align-items: center; gap: 10px 16px; margin-bottom: 8px; }
.batch-key { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 0; }
.census-toggle { margin-top: 8px; }
.census-table { margin-top: 8px; }
.legend-block { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px; margin-bottom: 8px; }
.legend-row { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 0; }
.legend-note { width: 100%; margin: 0; }
.legend-bit { display: inline-flex; align-items: center; gap: 6px; }
.legend-bit i { width: 10px; height: 10px; display: inline-block; }
.cell-warn { background: color-mix(in srgb, var(--c-warn) 22%, transparent); }
.rh { display: flex; align-items: flex-start; gap: 10px; padding-bottom: 4px; }
.rh h1 { font-size: var(--fs-xl); font-family: var(--font-mono); margin: 2px 0; }
.batch-sum + .batch-sum { margin-top: 14px; }
.sum { margin: 4px 0 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px; line-height: 1.7; }
.chart-row { margin-top: 12px; }
.preset-row { display: flex; flex-wrap: wrap; gap: 6px; }
.figure { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
.figure-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.figure-grid.stack { grid-template-columns: 1fr; }
.png { width: 100%; max-height: 640px; object-fit: contain; }
.ask { display: flex; flex-direction: column; gap: 8px; }
.figure-status { display: inline-flex; align-items: center; gap: 6px; }
.spin { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 800px) {
  .figure-grid { grid-template-columns: 1fr; }
}
</style>
