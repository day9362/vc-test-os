<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Coins, Download, Gauge, Layers, ListTree, PhoneCall, Timer } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Panel from '@/components/Panel.vue'
import Kpi from '@/components/Kpi.vue'
import EChart from '@/components/EChart.vue'
import { useTokens } from '@/composables/useTokens'
import { useAppStore } from '@/stores/app'
import { api } from '@/api/http'
import { dt } from '@/utils/format'
import type { AiModule } from '@/api/types'

interface AiModuleRow {
  id: AiModule
  name: string
  where: string
  desc: string
  model: string
  trigger: string
}
interface UsageModule {
  module: AiModule
  model: string
  calls: number
  input: number
  output: number
  total: number
  cost_cny: number
}
interface UsageSummary {
  days: number
  total: number
  input: number
  output: number
  calls: number
  cost_cny: number
  month: { used: number; budget: number; alert_pct: number; paused: boolean }
  by_module: UsageModule[]
}
interface UsageDay { ts: number; by_module: Record<string, number> }
interface AiCall {
  id: string
  time: number
  module: AiModule
  user: string
  input: number
  output: number
  latency_ms: number
  ok: boolean
}

const tk = useTokens()
const app = useAppStore()
const range = ref<7 | 30>(30)
const modules = ref<AiModuleRow[]>([])
const summary = ref<UsageSummary | null>(null)
const days = ref<UsageDay[]>([])
const calls = ref<AiCall[]>([])
const loadError = ref('')

const perModule = computed(() => (summary.value?.by_module ?? []).map((row) => {
  const meta = modules.value.find((item) => item.id === row.module)
  return {
    id: row.module,
    name: meta?.name ?? row.module,
    where: meta?.where ?? '',
    desc: meta?.desc ?? '',
    trigger: meta?.trigger ?? '用户',
    model: row.model,
    calls: row.calls,
    total: row.total,
    input: row.input,
    output: row.output,
    cost: row.cost_cny,
  }
}))
const total = computed(() => summary.value?.total ?? 0)
const totalIn = computed(() => summary.value?.input ?? 0)
const totalOut = computed(() => summary.value?.output ?? 0)
const cost = computed(() => summary.value?.cost_cny ?? 0)
const callCount = computed(() => summary.value?.calls ?? 0)
const monthUsed = computed(() => summary.value?.month.used ?? 0)
const budget = computed(() => summary.value?.month.budget ?? 0)
const alertPct = computed(() => summary.value?.month.alert_pct ?? 80)
const paused = computed(() => summary.value?.month.paused ?? false)
const budgetPct = computed(() => budget.value > 0 ? (monthUsed.value / budget.value) * 100 : 0)
const inShare = computed(() => total.value > 0 ? (totalIn.value / total.value) * 100 : 0)
const fmt = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(Math.round(n)))
const nameOf = (id: string) => modules.value.find((item) => item.id === id)?.name ?? id

async function load() {
  loadError.value = ''
  try {
    const [moduleRows, usage, daily, page] = await Promise.all([
      api<AiModuleRow[]>('/ai/modules'),
      api<UsageSummary>(`/ai/usage/summary?days=${range.value}`),
      api<UsageDay[]>(`/ai/usage/daily?days=${range.value}`),
      api<{ items: AiCall[] }>(`/ai/calls?limit=50`),
    ])
    modules.value = moduleRows
    summary.value = usage
    days.value = daily
    calls.value = page.items
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : '用量没有读到'
  }
}

function exportCsv() {
  if (!calls.value.length) {
    app.toast({ kind: 'danger', title: '没有可导出的调用' })
    return
  }
  const header = ['时间', '调用 ID', '模块', '发起人', '模型', '输入', '输出', '耗时毫秒', '结果']
  const lines = calls.value.map((item) => [
    dt(item.time), item.id, nameOf(item.module), item.user, item.model, item.input, item.output, item.latency_ms, item.ok ? '成功' : '失败',
  ].map((value) => {
    const text = String(value)
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
  }).join(','))
  const blob = new Blob([`\uFEFF${[header.join(','), ...lines].join('\r\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'ai_calls.csv'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  app.toast({ kind: 'ok', title: '已导出调用明细', desc: `ai_calls.csv · ${calls.value.length} 条` })
}

const dailyOpt = computed(() => {
  const t = tk.value
  return {
    grid: { left: 48, right: 12, top: 30, bottom: 24 },
    legend: { data: perModule.value.map((item) => item.name) },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmt(v) },
    xAxis: { type: 'category', data: days.value.map((row) => dt(row.ts).slice(0, 5)) },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmt(v) } },
    series: perModule.value.map((item, index) => ({
      name: item.name,
      type: 'bar',
      stack: 't',
      barWidth: '60%',
      data: days.value.map((row) => row.by_module[item.id] ?? 0),
      itemStyle: { color: t.chart[index % 6] },
    })),
  }
})
const pieOpt = computed(() => {
  const t = tk.value
  return {
    tooltip: { trigger: 'item', valueFormatter: (v: number) => fmt(v) },
    legend: { show: false },
    series: [{
      type: 'pie', radius: ['48%', '78%'], center: ['50%', '52%'], itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 0 },
      label: { formatter: '{b}\n{d}%', fontSize: 11, color: t['text-2'] },
      data: perModule.value.filter((item) => item.total > 0).map((item, index) => ({ name: item.name, value: item.total, itemStyle: { color: t.chart[index % 6] } })),
    }],
  }
})

onMounted(load)
watch(range, load)
</script>

<template>
  <div class="page">
    <PageHeader title="Token 统计" desc="平台内所有 AI 调用都经本地后端统一转发并记录到 ai_calls 表">
      <div class="seg" role="group" aria-label="时间范围">
        <button :aria-pressed="range === 7" @click="range = 7">近 7 天</button>
        <button :aria-pressed="range === 30" @click="range = 30">近 30 天</button>
      </div>
      <button class="btn" @click="exportCsv"><Download :size="16" />导出</button>
    </PageHeader>

    <p v-if="loadError" class="t-danger">{{ loadError }} <button class="btn btn-sm" @click="load">重试</button></p>
    <p v-if="paused" class="t-danger">本月预算已用完。自动归因已暂停，手动发起的方案、对话和报告仍可使用。</p>

    <div class="grid g-5">
      <Kpi label="Token 总量" :value="fmt(total)" :icon="Coins" :sub="`近 ${range} 天 · ${perModule.length} 个模块`" />
      <Kpi label="输入 / 输出" :value="total ? `${inShare.toFixed(0)} : ${(100 - inShare).toFixed(0)}` : '—'" :icon="Layers" :sub="`入 ${fmt(totalIn)} · 出 ${fmt(totalOut)}`" />
      <Kpi label="调用次数" :value="callCount.toLocaleString()" :icon="PhoneCall" :sub="`日均 ${Math.round(callCount / range)}`" />
      <Kpi label="估算费用" :value="cost.toFixed(1)" unit="元" :icon="Gauge" sub="按各模型公开单价" />
      <div class="budget" :class="budgetPct >= alertPct ? 'warn' : ''">
        <div class="row-between"><span class="fs-sm text-2">本月预算</span><Timer :size="16" class="muted" /></div>
        <div class="row" style="align-items: baseline"><b class="num">{{ budget ? budgetPct.toFixed(1) : '—' }}</b><span class="fs-sm muted">%</span></div>
        <div class="bar" :class="budgetPct >= alertPct ? 'warn' : ''"><i :style="{ width: `${Math.min(100, budgetPct)}%` }" /><span class="mk" :style="{ left: `${alertPct}%` }" /></div>
        <span class="fs-xs muted num">{{ fmt(monthUsed) }} / {{ fmt(budget) }} · {{ alertPct }}% 时提醒</span>
      </div>
    </div>

    <div class="grid g-3">
      <Panel class="span-2" title="每日用量" code="BY MODULE" :icon="Coins"><EChart :option="dailyOpt" :height="260" /></Panel>
      <Panel title="模块占比" code="SHARE" :icon="Layers"><EChart :option="pieOpt" :height="260" /></Panel>
    </div>

    <Panel title="AI 模块" code="WHERE AI LIVES" :icon="ListTree" flush>
      <div class="table-wrap" style="border-top: 0">
        <table class="table">
          <thead><tr><th>模块</th><th>所在页面</th><th>做什么</th><th>模型</th><th>触发</th><th class="r">调用</th><th class="r">Token</th><th style="width: 160px">占比</th><th class="r">费用</th></tr></thead>
          <tbody>
            <tr v-if="!perModule.length"><td colspan="9" class="c muted">还没有读到模块</td></tr>
            <tr v-for="(m, i) in perModule" :key="m.id">
              <td><span class="sw" :style="{ background: tk.chart[i % 6] }" /><b>{{ m.name }}</b> <span class="mono fs-xs muted">{{ m.id }}</span></td>
              <td class="fs-sm">{{ m.where }}</td>
              <td class="fs-sm text-2" style="white-space: normal; min-width: 260px">{{ m.desc }}</td>
              <td class="mono fs-sm">{{ m.model || '—' }}</td>
              <td><span class="tag" :class="m.trigger === '自动' ? 'info' : m.trigger === '用户' ? '' : 'primary'">{{ m.trigger }}</span></td>
              <td class="r num">{{ m.calls.toLocaleString() }}</td>
              <td class="r num">{{ fmt(m.total) }}</td>
              <td><div class="row gap-4"><div class="bar grow"><i :style="{ width: `${total ? (m.total / total) * 100 : 0}%`, background: tk.chart[i % 6] }" /></div><span class="num fs-xs" style="width: 40px; text-align: right">{{ total ? ((m.total / total) * 100).toFixed(1) : '0.0' }}%</span></div></td>
              <td class="r num">{{ m.cost.toFixed(1) }} 元</td>
            </tr>
          </tbody>
        </table>
      </div>
      <template #footer>「自动」模块由告警触发，不经用户发起。用满月度预算后自动归因暂停，手动发起的模块仍可用</template>
    </Panel>

    <Panel title="最近调用" code="AI_CALLS" :icon="PhoneCall" flush>
      <div class="table-wrap" style="border-top: 0; max-height: 360px">
        <table class="table">
          <thead><tr><th>时间</th><th>调用 ID</th><th>模块</th><th>发起人</th><th class="r">输入</th><th class="r">输出</th><th class="r">耗时</th><th>结果</th></tr></thead>
          <tbody>
            <tr v-if="!calls.length"><td colspan="8" class="c muted">还没有 AI 调用</td></tr>
            <tr v-for="c in calls" :key="c.id">
              <td class="num fs-sm">{{ dt(c.time) }}</td>
              <td class="mono fs-xs">{{ c.id }}</td>
              <td>{{ nameOf(c.module) }}</td>
              <td class="fs-sm">{{ c.user }}</td>
              <td class="r num">{{ c.input.toLocaleString() }}</td>
              <td class="r num">{{ c.output.toLocaleString() }}</td>
              <td class="r num">{{ (c.latency_ms / 1000).toFixed(1) }} s</td>
              <td><span class="tag" :class="c.ok ? 'ok' : 'danger'">{{ c.ok ? '成功' : '失败' }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>
  </div>
</template>

<style scoped>
.budget { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; background: var(--c-surface); border: var(--bw) solid var(--c-border); box-shadow: inset 0 3px 0 var(--c-ok); }
.budget.warn { box-shadow: inset 0 3px 0 var(--c-warn); }
.budget b { font-size: var(--fs-2xl); line-height: 1.15; }
.budget .bar { overflow: visible; margin: 4px 0; }
.mk { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--c-text); }
.sw { display: inline-block; width: 8px; height: 8px; margin-right: 6px; }
</style>
