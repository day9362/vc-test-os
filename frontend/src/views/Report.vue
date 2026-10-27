<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, BarChart3, Download } from 'lucide-vue-next'
import Kpi from '@/components/Kpi.vue'
import Panel from '@/components/Panel.vue'
import EChart from '@/components/EChart.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api } from '@/api/http'
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

async function load() {
  if (!asked.value.length) {
    report.value = null
    error.value = '没有指定批次'
    return
  }
  loading.value = true
  error.value = ''
  try {
    report.value = await api<ReportData>(`/reports/data?batch_ids=${encodeURIComponent(asked.value.join(','))}`)
  } catch (err) {
    report.value = null
    error.value = err instanceof Error ? err.message : '报告加载失败'
  } finally {
    loading.value = false
  }
}
watch(() => route.query.b, load, { immediate: true })

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

const finding = computed(() => {
  const data = report.value
  const s = data?.summary
  if (!data || !s?.tested) return []
  const lines = [`测了 ${s.tested} 片：合格 ${s.passed}，不合格 ${s.failed}，中止 ${s.aborted}，良率 ${s.yield_rate.toFixed(2)}%。`]
  const top = data.fail_pareto[0]
  if (top) lines.push(`不合格集中在 ${top.item}，${top.count} 片。`)
  else if (!s.failed && !s.aborted) lines.push('没有不合格，也没有中止。')
  const ranked = data.machine_yield.filter((item) => item.n > 0)
  const worst = [...ranked].sort((a, b) => a.passed / a.n - b.passed / b.n)[0]
  if (worst && ranked.length > 1) {
    lines.push(`${worst.machine_id} 良率最低，${worst.passed}/${worst.n}。`)
  }
  if (hasRc.value) lines.push(`Rc 均值 ${s.rc_mean.toFixed(3)} ℃/W，标准差 ${s.rc_sd.toFixed(3)}。`)
  else lines.push('设备没有返回热阻，Rc 先空着。')
  if (s.cpk_t01 != null) lines.push(`T0−T1 的 Cpk 是 ${s.cpk_t01.toFixed(2)}，上限 ${s.usl_t01} ℃。`)
  const profile = hottest(data)
  if (profile) lines.push(`温差最大的是 ${profile.item}，均值 ${profile.value.toFixed(3)} ℃。`)
  return lines
})

async function exportPdf() {
  if (!asked.value.length) return
  try {
    const body = await api<{ url: string }>('/reports/export', {
      method: 'POST',
      body: JSON.stringify({ batch_ids: asked.value, figure_ids: [], format: 'pdf' }),
    })
    const link = document.createElement('a')
    link.href = body.url
    link.download = `${multi.value ? 'combined' : asked.value[0]}.pdf`
    link.click()
    app.toast({ kind: 'ok', title: '报告已导出', desc: body.url })
  } catch (err) {
    app.toast({ kind: 'danger', title: '导出失败', desc: err instanceof Error ? err.message : '报告没有导出' })
  }
}

function hottest(data: ReportData) {
  let item = ''
  let value = -Infinity
  for (const values of Object.values(data.delta_profile.mean)) {
    for (let index = 0; index < values.length; index += 1) {
      const current = values[index]
      if (current != null && current > value) {
        value = current
        item = data.delta_profile.items[index]
      }
    }
  }
  return item ? { item, value } : null
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

const rcHistOpt = computed(() => {
  const t = tk.value
  const hist = report.value?.rc_histogram
  if (!hist?.edges.length) return null
  const labels = hist.edges.slice(0, -1).map((edge, index) => ((edge + hist.edges[index + 1]) / 2).toFixed(2))
  return {
    grid: { left: 40, right: 12, top: multi.value ? 30 : 14, bottom: 34 },
    legend: { show: multi.value },
    xAxis: { type: 'category', data: labels, name: 'Rc ℃/W', nameLocation: 'middle', nameGap: 22 },
    yAxis: { type: 'value', name: '片' },
    series: Object.entries(hist.counts).map(([id, counts], index) => ({
      name: id, type: 'bar', data: counts, itemStyle: { color: t.chart[index % 6], opacity: multi.value ? 0.65 : 1 },
    })),
  }
})

const paretoOpt = computed(() => {
  const t = tk.value
  const rows = report.value?.fail_pareto ?? []
  if (!rows.length) return null
  const total = rows.reduce((sum, row) => sum + row.count, 0)
  let acc = 0
  const rate = rows.map((row) => { acc += row.count; return +((acc / total) * 100).toFixed(1) })
  return {
    grid: { left: 36, right: 40, top: 26, bottom: 44 },
    legend: { data: ['不合格片数', '累计占比'] },
    xAxis: { type: 'category', data: rows.map((row) => row.item), axisLabel: { interval: 0, rotate: 20 } },
    yAxis: [{ type: 'value', name: '片' }, { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } }],
    series: [
      { name: '不合格片数', type: 'bar', data: rows.map((row) => row.count), itemStyle: { color: t.danger } },
      { name: '累计占比', type: 'line', yAxisIndex: 1, data: rate, itemStyle: { color: t.chart[1] } },
    ],
  }
})

const profileOpt = computed(() => {
  const t = tk.value
  const profile = report.value?.delta_profile
  if (!profile?.items.length) return null
  const series = list.value.map((batch, index) => ({
    name: batch.batch_id, type: 'line', data: profile.mean[batch.batch_id] ?? [], itemStyle: { color: t.chart[index % 6] },
  }))
  if (profile.p95) series.push({ name: 'P95', type: 'line', data: profile.p95, itemStyle: { color: t.warn } })
  if (profile.limit.some((value) => value != null)) {
    series.push({ name: '上限', type: 'line', data: profile.limit, itemStyle: { color: t.danger } })
  }
  return {
    grid: { left: 40, right: 12, top: 30, bottom: 24 },
    legend: { type: 'scroll' },
    xAxis: { type: 'category', data: profile.items },
    yAxis: { type: 'value', name: '℃' },
    series,
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

      <Panel v-if="finding.length" title="结果" code="FROM RUNS">
        <ol class="sum">
          <li v-for="(line, index) in finding" :key="index">{{ line }}</li>
        </ol>
      </Panel>

      <Panel v-if="multi" title="批次对比" code="YIELD · RC" :icon="BarChart3">
        <EChart :option="compareOpt" :height="240" />
      </Panel>

      <div v-if="list.length" class="grid g-2">
        <Panel title="分机台良率" code="BY MACHINE" :icon="BarChart3">
          <EChart v-if="report?.machine_yield.length" :option="machineYieldOpt" :height="240" />
          <p v-else class="muted">没有机台记录。</p>
        </Panel>
        <Panel title="Rc 分布" code="(T1−Ta)/P" :icon="BarChart3">
          <EChart v-if="rcHistOpt" :option="rcHistOpt" :height="240" />
          <p v-else class="muted">设备没有返回热阻。</p>
        </Panel>
        <Panel title="不合格项" code="FAIL ITEMS" :icon="BarChart3">
          <EChart v-if="paretoOpt" :option="paretoOpt" :height="240" />
          <p v-else class="muted">没有不合格项。</p>
        </Panel>
        <Panel title="温差" code="T1−Tx" :icon="BarChart3">
          <EChart v-if="profileOpt" :option="profileOpt" :height="240" />
          <p v-else class="muted">没有温差数据。</p>
        </Panel>
      </div>

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
    </template>
  </div>
</template>

<style scoped>
.rh { display: flex; align-items: flex-start; gap: 10px; padding-bottom: 4px; }
.rh h1 { font-size: var(--fs-xl); font-family: var(--font-mono); margin: 2px 0; }
.sum { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px; line-height: 1.7; }
</style>
