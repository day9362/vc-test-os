<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, BarChart3, Bot, Download, Sparkles } from 'lucide-vue-next'
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
  process: { serial_number: string; item: string; shape: string }[]
}
const analysis = ref<AnalysisData | null>(null)
const analysisTarget = ref<'product' | 'machine'>('product')
const summaryLines = ref<string[]>([])
const summaryModel = ref('')
const summaryError = ref('')
const summaryBusy = ref(false)
interface FigurePanel {
  title: string
  option: Record<string, unknown>
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
  summaryError.value = ''
  figures.value = []
  figureError.value = ''
  try {
    const query = encodeURIComponent(asked.value.join(','))
    report.value = await api<ReportData>(`/reports/data?batch_ids=${query}`)
    analysis.value = await api<AnalysisData>(`/reports/analysis?batch_ids=${query}`).catch(() => null)
    await loadFigures().catch(() => { figures.value = [] })
    await loadSavedSummary().catch(() => { summaryLines.value = [] })
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
function sliceItem(slice: AnalysisSlice, name: string) {
  return slice.items.find((item) => item.item === name)
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

async function loadSummary() {
  if (!asked.value.length || summaryBusy.value) return
  summaryBusy.value = true
  summaryError.value = ''
  try {
    const body = await api<{ lines: string[]; model: string }>('/reports/summary', {
      method: 'POST',
      body: JSON.stringify({ batch_ids: asked.value }),
    })
    summaryLines.value = body.lines
    summaryModel.value = body.model
  } catch (err) {
    summaryLines.value = []
    summaryModel.value = ''
    summaryError.value = err instanceof Error ? err.message : '总结没有生成'
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
  try {
    const created = await api<{ figure_id: string }>('/reports/figures', {
      method: 'POST',
      body: JSON.stringify({ batch_ids: asked.value, prompt, preset: kind }),
    })
    if (!kind) figurePrompt.value = ''
    await loadFigures()
    await followFigure(created.figure_id)
  } catch (err) {
    figureError.value = err instanceof Error ? err.message : '分析没有开始'
  } finally {
    figureBusy.value = false
  }
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
  if (summaryError.value) blocks.push({ kind: 'text', text: summaryError.value })
  else if (summaryLines.value.length) summaryLines.value.forEach((line, index) => blocks.push({ kind: 'text', text: `${index + 1}. ${line}` }))
  else blocks.push({ kind: 'text', text: '还没有生成总结。' })
  if (limitFailOpt.value) add(shot('limitFail', '超上限、超下限'))
  if (limitMeanOpt.value) add(shot('limitMean', '均值、最小值、最大值、上限、下限'))
  if (splitOpt.value) add(shot('split', `相关性 · 同一项在${acrossLabel.value}的均值`))
  else if (analysis.value && !analysis.value.note) blocks.push({ kind: 'text', text: analysisTarget.value === 'product' ? '现在只选了这一批。再选一批，才能把同一项按批次横向对比。' : '现在只有一个槽位，没有可横向对比的对象。' })
  if (analysis.value) {
    const current = analysis.value
    blocks.push({ kind: 'h2', text: '卡限项分析' })
    blocks.push({ kind: 'text', text: `有效 ${current.tested} 片 · 中止 ${current.aborted} · 未保留 ${current.discarded} · 无效读数 ${current.invalid}` })
    if (current.note) blocks.push({ kind: 'text', text: current.note })
    else if (current.overall.items.length) {
      blocks.push({
        kind: 'table',
        title: '卡限项',
        columns: ['项', '片数', '均值', '最小值', '最大值', '极差', '重复性', '超上限', '超下限', '偏移', '上限裕量', '下限裕量', '时间顺序'],
        rows: current.overall.items.map((item) => [
          item.item,
          String(item.n),
          meas(item.item, item.mean),
          meas(item.item, item.minimum),
          meas(item.item, item.maximum),
          meas(item.item, item.range),
          item.retest_serials ? `${meas(item.item, item.repeat_std)} 复测极差 ${meas(item.item, item.retest_range)}` : meas(item.item, item.repeat_std),
          String(item.high_fail),
          String(item.low_fail),
          item.offset,
          meas(item.item, item.margin_high),
          meas(item.item, item.margin_low),
          item.trend,
        ]),
      })
    } else blocks.push({ kind: 'text', text: '方案里没有可分析的上下限' })
    if (acrossSlices.value.length > 1) {
      const rows: string[][] = []
      for (const name of orderedItemNames.value) {
        for (const slice of acrossSlices.value) {
          const item = sliceItem(slice, name)
          rows.push([
            name,
            slice.name,
            String(item?.n ?? 0),
            meas(name, item?.mean),
            meas(name, item?.minimum),
            meas(name, item?.maximum),
            meas(name, item?.range),
            String(item?.high_fail ?? 0),
            String(item?.low_fail ?? 0),
          ])
        }
      }
      blocks.push({ kind: 'table', title: `相关性 · 同一项在${acrossLabel.value}`, columns: ['项', '分组', '片数', '均值', '最小值', '最大值', '极差', '超上限', '超下限'], rows })
    }
    if (current.fail_rank.length) {
      blocks.push({ kind: 'h2', text: '不合格项' })
      blocks.push({ kind: 'text', text: failText.value })
    }
    for (const slice of shownSlices.value) {
      blocks.push({ kind: 'text', text: `${slice.name} 中止 ${slice.aborted} · 未保留 ${slice.discarded}` })
      for (const item of slice.items.filter((row) => row.high_fail || row.low_fail || slice.items.length <= 6)) {
        blocks.push({ kind: 'text', text: `${item.item} 均值 ${meas(item.item, item.mean)}，极差 ${meas(item.item, item.range)}，超上限 ${item.high_fail} 片，超下限 ${item.low_fail} 片，${item.offset}` })
      }
    }
    if (analysisTarget.value === 'machine' && current.slots.length) {
      blocks.push({ kind: 'h2', text: '槽位' })
      for (const slice of current.slots) {
        blocks.push({ kind: 'text', text: `${slice.name}：${slice.items.map((item) => `${item.item} 均值 ${meas(item.item, item.mean)} 极差 ${meas(item.item, item.range)}`).join('；')}` })
      }
    }
    if (current.process.length) {
      blocks.push({ kind: 'h2', text: '过程' })
      for (const note of current.process) blocks.push({ kind: 'text', text: `${note.serial_number} 的 ${note.item}：${note.shape}` })
    }
  }
  if (findings.value.length) {
    blocks.push({ kind: 'h2', text: '结果' })
    for (const section of findings.value) {
      if (findings.value.length > 1) blocks.push({ kind: 'text', text: section.batch_id })
      section.lines.forEach((line, index) => blocks.push({ kind: 'text', text: `${index + 1}. ${line}` }))
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
      blocks.push({ kind: 'h2', text: item.title || item.prompt })
      if (item.status === 'running') blocks.push({ kind: 'text', text: item.step || '正在分析' })
      if (item.error) blocks.push({ kind: 'text', text: item.error })
      if (item.panels?.length) item.panels.forEach((panel, index) => add(shot(`fig-${item.figure_id}-${index}`, panel.title || item.title || '补充分析')))
      else if (item.echarts_option) add(shot(`fig-${item.figure_id}`, item.title || '补充分析'))
      if (item.summary) {
        blocks.push({ kind: 'text', text: item.summary.scope })
        if (item.summary.rows.length) blocks.push({ kind: 'table', columns: item.summary.columns, rows: item.summary.rows })
        item.summary.notes.forEach((note) => blocks.push({ kind: 'text', text: note }))
      } else item.results.forEach((pair) => blocks.push({ kind: 'text', text: `${pair[0]}：${pair[1]}` }))
    }
  }
  return blocks.slice(0, 120)
}

function seriesType(panel: FigurePanel) {
  const series = panel.option?.series
  const first = Array.isArray(series) ? series[0] : null
  return String(first?.type || '')
}

function panelIsWide(panel: FigurePanel) {
  const kind = seriesType(panel)
  if (kind === 'heatmap' || kind === 'boxplot') return true
  if (Array.isArray(panel.option?.yAxis) && panel.option.yAxis.length > 1) return true
  const data = panel.option?.xAxis?.data
  return Array.isArray(data) && data.length > 4
}

function stackPanels(panels: FigurePanel[]) {
  return panels.length !== 2 || panels.some(panelIsWide)
}

function panelHeight(panel: FigurePanel) {
  const kind = seriesType(panel)
  const across = panel.option?.xAxis?.data
  const down = Array.isArray(panel.option?.yAxis) ? [] : panel.option?.yAxis?.data
  const count = Math.max(Array.isArray(across) ? across.length : 0, Array.isArray(down) ? down.length : 0)
  if (kind === 'heatmap') return Math.min(520, Math.max(320, 140 + count * 36))
  if (kind === 'boxplot') return 320
  if (Array.isArray(panel.option?.yAxis)) return 300
  return count > 6 ? 320 : 280
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

const machineYieldOpt = computed(() => {
  const t = tk.value
  const rows = report.value?.machine_yield ?? []
  const rates = rows.map((row) => +((row.passed / Math.max(1, row.n)) * 100).toFixed(2))
  return {
    grid: { left: 40, right: 12, top: 18, bottom: 24 },
    xAxis: { type: 'category', data: rows.map((row) => row.machine_id) },
    yAxis: { type: 'value', min: rates.length ? Math.min(90, Math.floor(Math.min(...rates) / 5) * 5) : 0, max: 100 },
    series: [{
      type: 'bar', barWidth: '50%',
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
  const means = [...grouped.values()].map((rows) => +(rows.reduce((sum, value) => sum + value, 0) / rows.length).toFixed(3))
  const spec = analysis.value?.overall.items.find((item) => item.item === 'Temp_T0-T1')
  const limitText = (name: string, value: number | null | undefined) => value == null ? `${name} —` : `${name} ${value.toFixed(3)} ℃`
  return {
    grid: { left: 48, right: 16, top: 28, bottom: 36 },
    tooltip: {
      trigger: 'axis',
      formatter: (raw: unknown) => {
        const row = (Array.isArray(raw) ? raw[0] : raw) as { axisValue?: string; data?: { value?: number; n?: number }; marker?: string }
        return [
          row.axisValue ?? '',
          `${row.marker ?? ''}均值 ${row.data?.value ?? ''} ℃`,
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
      label: { show: true, position: 'top', fontSize: 11, color: t['text-2'], formatter: (item: { value?: number }) => `${Number(item.value).toFixed(3)} ℃` },
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
        const body = visible.map((row) => `${row.marker ?? ''}${row.seriesName ?? ''} ${row.data?.serial ?? ''} ${row.value} ℃`)
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
      { name: '不合格片数', type: 'bar', data: rows.map((row) => row.count), itemStyle: { color: t.danger } },
      { name: '占本批', type: 'line', yAxisIndex: 1, data: rate, itemStyle: { color: t.chart[1] } },
    ],
  }
})

const profileOpt = computed(() => {
  const t = tk.value
  const profile = report.value?.delta_profile
  if (!profile?.items.length) return null
  const series = list.value.map((batch, index) => ({
    name: batch.batch_id, type: 'line', connectNulls: false, data: profile.mean[batch.batch_id] ?? [], itemStyle: { color: t.chart[index % 6] },
  }))
  if (profile.p95) series.push({ name: 'P95', type: 'line', connectNulls: false, data: profile.p95, itemStyle: { color: t.warn } })
  if (profile.limit.some((value) => value != null)) {
    series.push({
      name: '上限', type: 'line', connectNulls: false, showSymbol: true, symbol: 'circle', symbolSize: 6,
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
  if (!items.length) return null
  const t = tk.value
  return {
    grid: { left: 36, right: 12, top: 28, bottom: 48 },
    legend: { data: ['超上限', '超下限'] },
    xAxis: { type: 'category', data: items.map((item) => item.item), axisLabel: { interval: 0, rotate: 18 } },
    yAxis: { type: 'value', name: '片', minInterval: 1 },
    series: [
      { name: '超上限', type: 'bar', data: items.map((item) => item.high_fail), itemStyle: { color: t.danger } },
      { name: '超下限', type: 'bar', data: items.map((item) => item.low_fail), itemStyle: { color: t.chart[1] } },
    ],
  }
})

const limitMeanOpt = computed(() => {
  const items = analysis.value?.overall.items ?? []
  if (!items.length) return null
  const t = tk.value
  return {
    grid: { left: 44, right: 12, top: 28, bottom: 48 },
    legend: { data: ['均值', '最大值', '最小值', '上限', '下限'] },
    xAxis: { type: 'category', data: items.map((item) => item.item), axisLabel: { interval: 0, rotate: 18 } },
    yAxis: { type: 'value' },
    series: [
      { name: '均值', type: 'bar', data: items.map((item) => item.mean), itemStyle: { color: t.chart[0] } },
      { name: '最大值', type: 'line', data: items.map((item) => item.maximum), symbol: 'triangle', symbolSize: 9, itemStyle: { color: t.chart[2] } },
      { name: '最小值', type: 'line', data: items.map((item) => item.minimum), symbol: 'diamond', symbolSize: 8, itemStyle: { color: t.chart[4] } },
      { name: '上限', type: 'line', data: items.map((item) => item.high), symbol: 'none', itemStyle: { color: t.danger } },
      { name: '下限', type: 'line', data: items.map((item) => item.low), symbol: 'none', itemStyle: { color: t.warn } },
    ],
  }
})

const splitOpt = computed(() => {
  const data = analysis.value
  const slices = acrossSlices.value
  if (!data || data.note || slices.length < 2) return null
  const names = orderedItemNames.value
  if (!names.length) return null
  const t = tk.value
  return {
    grid: { left: 44, right: 12, top: 28, bottom: 48 },
    legend: { type: 'scroll' },
    xAxis: { type: 'category', data: slices.map((slice) => slice.name), axisLabel: { interval: 0, rotate: 18 } },
    yAxis: { type: 'value', name: '均值' },
    series: names.map((name, index) => ({
      name,
      type: 'bar',
      data: slices.map((slice) => sliceItem(slice, name)?.mean ?? null),
      itemStyle: { color: t.chart[index % 6] },
    })),
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
      { name: '良率', type: 'bar', data: rows.map((row) => row.yield_rate), itemStyle: { color: t.chart[0] } },
      { name: 'Rc 均值', type: 'line', yAxisIndex: 1, data: rows.map((row) => row.rc_mean || null), itemStyle: { color: t.chart[2] } },
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
        <template #actions>
          <button type="button" class="btn btn-sm" :disabled="summaryBusy" @click="loadSummary">{{ summaryBusy ? '正在写…' : '生成总结' }}</button>
        </template>
        <div class="row">
          <div class="seg">
            <button type="button" :aria-pressed="analysisTarget === 'product'" @click="analysisTarget = 'product'">产品</button>
            <button type="button" :aria-pressed="analysisTarget === 'machine'" @click="analysisTarget = 'machine'">机台</button>
          </div>
        </div>
        <p v-if="summaryError" class="t-danger">{{ summaryError }}</p>
        <ol v-else-if="summaryLines.length" class="sum">
          <li v-for="(line, index) in summaryLines" :key="index">{{ line }}</li>
        </ol>
        <p v-else class="muted">总结只用下面这套词：片、不合格、均值、极差、最大值、最小值、上限、下限、超上限、超下限、偏上限、偏下限、上限裕量、下限裕量。温度带 ℃，功率带 W。</p>
        <div v-if="limitFailOpt || limitMeanOpt" class="grid g-2 chart-row">
          <div v-if="limitFailOpt">
            <p class="fs-sm fw-6">超上限、超下限</p>
            <EChart :ref="(el) => takeChart('limitFail', el)" :option="limitFailOpt" :height="220" />
          </div>
          <div v-if="limitMeanOpt">
            <p class="fs-sm fw-6">均值、最小值、最大值、上限、下限</p>
            <EChart :ref="(el) => takeChart('limitMean', el)" :option="limitMeanOpt" :height="220" />
          </div>
        </div>
        <div v-if="splitOpt" class="chart-row">
          <p class="fs-sm fw-6">相关性 · 同一项在{{ acrossLabel }}的均值</p>
          <EChart :ref="(el) => takeChart('split', el)" :option="splitOpt" :height="220" />
        </div>
        <p v-else-if="analysis && !analysis.note" class="fs-sm muted">{{ analysisTarget === 'product' ? '现在只选了这一批。再选一批，才能把同一项按批次横向对比。' : '现在只有一个槽位，没有可横向对比的对象。' }}</p>
        <p v-if="summaryModel" class="fs-xs muted">{{ summaryModel }}</p>
      </Panel>

      <Panel v-if="analysis" title="卡限项分析" code="LIMITS" :icon="BarChart3">
        <p class="fs-xs muted">有效 {{ analysis.tested }} 片 · 中止 {{ analysis.aborted }} · 未保留 {{ analysis.discarded }} · 无效读数 {{ analysis.invalid }}</p>
        <p v-if="analysis.note" class="muted">{{ analysis.note }}</p>
        <div v-else class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>项</th><th class="r">片数</th><th class="r">均值</th><th class="r">最小值</th><th class="r">最大值</th><th class="r">极差</th><th class="r">重复性</th><th class="r">超上限</th><th class="r">超下限</th><th>偏移</th><th class="r">上限裕量</th><th class="r">下限裕量</th><th>时间顺序</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in analysis.overall.items" :key="item.item">
                <td class="mono fs-xs">{{ item.item }}</td>
                <td class="r num">{{ item.n }}</td>
                <td class="r num">{{ meas(item.item, item.mean) }}</td>
                <td class="r num">{{ meas(item.item, item.minimum) }}</td>
                <td class="r num">{{ meas(item.item, item.maximum) }}</td>
                <td class="r num">{{ meas(item.item, item.range) }}</td>
                <td class="r num">{{ meas(item.item, item.repeat_std) }}<span v-if="item.retest_serials" class="fs-xs muted"> 复测极差 {{ meas(item.item, item.retest_range) }}</span></td>
                <td class="r num">{{ item.high_fail }}</td>
                <td class="r num">{{ item.low_fail }}</td>
                <td>{{ item.offset }}</td>
                <td class="r num">{{ meas(item.item, item.margin_high) }}</td>
                <td class="r num">{{ meas(item.item, item.margin_low) }}</td>
                <td>{{ item.trend }}</td>
              </tr>
              <tr v-if="!analysis.overall.items.length"><td colspan="13" class="c muted">方案里没有可分析的上下限</td></tr>
            </tbody>
          </table>
        </div>
        <div v-if="acrossSlices.length > 1" class="table-wrap batch-sum">
          <p class="fs-sm fw-6">相关性 · 同一项在{{ acrossLabel }}</p>
          <table class="table">
            <thead>
              <tr><th>项</th><th>分组</th><th class="r">片数</th><th class="r">均值</th><th class="r">最小值</th><th class="r">最大值</th><th class="r">极差</th><th class="r">超上限</th><th class="r">超下限</th></tr>
            </thead>
            <tbody>
              <template v-for="name in orderedItemNames" :key="name">
                <tr v-for="slice in acrossSlices" :key="name + slice.name">
                  <td class="mono fs-xs">{{ name }}</td>
                  <td class="mono fs-xs">{{ slice.name }}</td>
                  <td class="r num">{{ sliceItem(slice, name)?.n ?? 0 }}</td>
                  <td class="r num">{{ meas(name, sliceItem(slice, name)?.mean) }}</td>
                  <td class="r num">{{ meas(name, sliceItem(slice, name)?.minimum) }}</td>
                  <td class="r num">{{ meas(name, sliceItem(slice, name)?.maximum) }}</td>
                  <td class="r num">{{ meas(name, sliceItem(slice, name)?.range) }}</td>
                  <td class="r num">{{ sliceItem(slice, name)?.high_fail ?? 0 }}</td>
                  <td class="r num">{{ sliceItem(slice, name)?.low_fail ?? 0 }}</td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <section v-if="analysis.fail_rank.length" class="batch-sum">
          <p class="fs-sm fw-6">不合格项</p>
          <p class="fs-sm">{{ failText }}</p>
        </section>
        <section v-for="slice in shownSlices" :key="slice.name" class="batch-sum">
          <p class="mono fs-sm fw-6">{{ slice.name }} <span class="muted">中止 {{ slice.aborted }} · 未保留 {{ slice.discarded }}</span></p>
          <p v-for="item in slice.items.filter((row) => row.high_fail || row.low_fail || slice.items.length <= 6)" :key="item.item" class="fs-sm">{{ item.item }} 均值 {{ meas(item.item, item.mean) }}，极差 {{ meas(item.item, item.range) }}，超上限 {{ item.high_fail }} 片，超下限 {{ item.low_fail }} 片，{{ item.offset }}</p>
        </section>
        <section v-if="analysisTarget === 'machine' && analysis.slots.length" class="batch-sum">
          <p class="fs-sm fw-6">槽位</p>
          <p v-for="slice in analysis.slots" :key="slice.name" class="fs-sm">{{ slice.name }}：{{ slice.items.map((item) => `${item.item} 均值 ${meas(item.item, item.mean)} 极差 ${meas(item.item, item.range)}`).join('；') }}</p>
        </section>
        <section v-if="analysis.process.length" class="batch-sum">
          <p class="fs-sm fw-6">过程</p>
          <p v-for="note in analysis.process" :key="note.serial_number + note.item" class="fs-sm">{{ note.serial_number }} 的 {{ note.item }}：{{ note.shape }}</p>
        </section>
      </Panel>

      <Panel v-if="findings.length" title="结果" code="FROM RUNS">
        <section v-for="section in findings" :key="section.batch_id" class="batch-sum">
          <p v-if="findings.length > 1" class="mono fs-sm fw-6">{{ section.batch_id }}</p>
          <ol class="sum">
            <li v-for="(line, index) in section.lines" :key="index">{{ line }}</li>
          </ol>
        </section>
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
        <article v-for="item in figures" :key="item.figure_id" class="figure">
          <div class="row-between">
            <b>{{ item.title || item.prompt }}</b>
            <button type="button" class="btn btn-ghost btn-sm" @click="removeFigure(item.figure_id)">移除</button>
          </div>
          <p v-if="item.status === 'running'" class="fs-sm muted">{{ item.step || '正在分析' }}</p>
          <p v-else-if="item.error" class="t-danger">{{ item.error }}</p>
          <div v-if="item.panels?.length" class="figure-grid" :class="{ stack: stackPanels(item.panels) }">
            <section v-for="(panel, index) in item.panels" :key="index">
              <p v-if="panel.title" class="fs-sm muted">{{ panel.title }}</p>
              <EChart :ref="(el) => takeChart(`fig-${item.figure_id}-${index}`, el)" :option="panel.option" :height="panelHeight(panel)" />
            </section>
          </div>
          <EChart v-else-if="item.echarts_option" :ref="(el) => takeChart(`fig-${item.figure_id}`, el)" :option="item.echarts_option" :height="240" />
          <img v-else-if="pngUrls[item.figure_id]" :src="pngUrls[item.figure_id]" alt="" class="png" />
          <p v-if="item.summary" class="fs-sm">{{ item.summary.scope }}</p>
          <div v-if="item.summary?.rows.length" class="table-wrap">
            <table class="table">
              <thead>
                <tr><th v-for="column in item.summary.columns" :key="column">{{ column }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="(row, index) in item.summary.rows" :key="index">
                  <td v-for="(cell, cellIndex) in row" :key="cellIndex" :class="cellIndex ? 'r num' : 'mono fs-xs'">{{ cell }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-for="note in item.summary?.notes || []" :key="note" class="fs-sm muted">{{ note }}</p>
          <table v-if="!item.summary && item.results.length" class="table">
            <tbody>
              <tr v-for="(pair, index) in item.results" :key="index"><td>{{ pair[0] }}</td><td class="num">{{ pair[1] }}</td></tr>
            </tbody>
          </table>
        </article>
      </Panel>
    </template>
  </div>
</template>

<style scoped>
.rh { display: flex; align-items: flex-start; gap: 10px; padding-bottom: 4px; }
.rh h1 { font-size: var(--fs-xl); font-family: var(--font-mono); margin: 2px 0; }
.batch-sum + .batch-sum { margin-top: 14px; }
.sum { margin: 4px 0 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px; line-height: 1.7; }
.chart-row { margin-top: 12px; }
.preset-row { display: flex; flex-wrap: wrap; gap: 6px; }
.figure { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
.figure-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.figure-grid.stack { grid-template-columns: 1fr; }
.png { width: 100%; max-height: 280px; object-fit: contain; }
@media (max-width: 800px) {
  .figure-grid { grid-template-columns: 1fr; }
}
</style>
