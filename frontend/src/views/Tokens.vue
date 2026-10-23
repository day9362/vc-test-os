<script setup lang="ts">
import { computed, ref } from 'vue'
import { Coins, Download, Gauge, Layers, ListTree, PhoneCall, Timer } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Panel from '@/components/Panel.vue'
import Kpi from '@/components/Kpi.vue'
import EChart from '@/components/EChart.vue'
import { useTokens } from '@/composables/useTokens'
import { useSettingsStore } from '@/stores/settings'
import { useAppStore } from '@/stores/app'
import { AI_MODULES, TOKEN_SHARE, tokenCalls, tokenDaily } from '@/mock/cluster'
import { dt } from '@/utils/format'
import type { AiModule } from '@/api/types'

const tk = useTokens()
const settings = useSettingsStore()
const app = useAppStore()

const range = ref<7 | 30>(30)
const daily = tokenDaily(30)
const calls = tokenCalls(40)
const rows = computed(() => daily.slice(-range.value))
const mods = AI_MODULES.map((m) => m.id)
const PRICE: Record<string, [number, number]> = { 'deepseek-v3': [2, 8], 'qwen3-max': [6, 24] } // 元 / 百万 token（入, 出）

const perModule = computed(() => mods.map((id) => {
  const total = rows.value.reduce((a, r) => a + r[id], 0)
  const [c, i, o] = TOKEN_SHARE[id]
  const inShare = i / (i + o)
  const m = AI_MODULES.find((x) => x.id === id)!
  const model = settings.saved.ai.models[id] ?? m.model
  const p = PRICE[model] ?? [4, 16]
  return { ...m, model, total, calls: Math.round(c * range.value * 0.82), input: total * inShare, output: total * (1 - inShare), cost: (total * inShare * p[0] + total * (1 - inShare) * p[1]) / 1e6 }
}))
const total = computed(() => perModule.value.reduce((a, m) => a + m.total, 0))
const totalIn = computed(() => perModule.value.reduce((a, m) => a + m.input, 0))
const cost = computed(() => perModule.value.reduce((a, m) => a + m.cost, 0))
const callCount = computed(() => perModule.value.reduce((a, m) => a + m.calls, 0))
const monthUsed = computed(() => daily.filter((r) => new Date(r.ts).getMonth() === new Date().getMonth()).reduce((a, r) => a + mods.reduce((s, id) => s + r[id], 0), 0))
const budget = computed(() => settings.saved.ai.monthly_budget_m * 1e6)
const budgetPct = computed(() => (monthUsed.value / budget.value) * 100)
const fmt = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(Math.round(n)))
const nameOf = (id: AiModule) => AI_MODULES.find((m) => m.id === id)!.name

const dailyOpt = computed(() => {
  const t = tk.value
  return {
    grid: { left: 48, right: 12, top: 30, bottom: 24 },
    legend: { data: AI_MODULES.map((m) => m.name) },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmt(v) },
    xAxis: { type: 'category', data: rows.value.map((r) => dt(r.ts).slice(0, 5)) },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmt(v) } },
    series: AI_MODULES.map((m, i) => ({ name: m.name, type: 'bar', stack: 't', barWidth: '60%', data: rows.value.map((r) => r[m.id]), itemStyle: { color: t.chart[i % 6] } })),
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
      data: perModule.value.map((m, i) => ({ name: m.name, value: m.total, itemStyle: { color: t.chart[i % 6] } })),
    }],
  }
})
</script>

<template>
  <div class="page">
    <PageHeader title="Token 统计" desc="平台内所有 AI 调用都经本地后端统一转发并记录到 ai_calls 表">
      <div class="seg" role="group" aria-label="时间范围">
        <button :aria-pressed="range === 7" @click="range = 7">近 7 天</button>
        <button :aria-pressed="range === 30" @click="range = 30">近 30 天</button>
      </div>
      <button class="btn" @click="app.toast({ kind: 'ok', title: '已导出调用明细', desc: 'ai_calls.csv' })"><Download :size="16" />导出</button>
    </PageHeader>

    <div class="grid g-5">
      <Kpi label="Token 总量" :value="fmt(total)" :icon="Coins" :sub="`近 ${range} 天 · ${AI_MODULES.length} 个模块`" />
      <Kpi label="输入 / 输出" :value="`${((totalIn / total) * 100).toFixed(0)} : ${(100 - (totalIn / total) * 100).toFixed(0)}`" :icon="Layers" :sub="`入 ${fmt(totalIn)} · 出 ${fmt(total - totalIn)}`" />
      <Kpi label="调用次数" :value="callCount.toLocaleString()" :icon="PhoneCall" :sub="`日均 ${Math.round(callCount / range)}`" />
      <Kpi label="估算费用" :value="cost.toFixed(1)" unit="元" :icon="Gauge" sub="按各模型公开单价" />
      <div class="budget" :class="budgetPct >= settings.saved.ai.alert_pct ? 'warn' : ''">
        <div class="row-between"><span class="fs-sm text-2">本月预算</span><Timer :size="16" class="muted" /></div>
        <div class="row" style="align-items: baseline"><b class="num">{{ budgetPct.toFixed(1) }}</b><span class="fs-sm muted">%</span></div>
        <div class="bar" :class="budgetPct >= settings.saved.ai.alert_pct ? 'warn' : ''"><i :style="{ width: `${Math.min(100, budgetPct)}%` }" /><span class="mk" :style="{ left: `${settings.saved.ai.alert_pct}%` }" /></div>
        <span class="fs-xs muted num">{{ fmt(monthUsed) }} / {{ fmt(budget) }} · {{ settings.saved.ai.alert_pct }}% 时提醒</span>
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
            <tr v-for="(m, i) in perModule" :key="m.id">
              <td><span class="sw" :style="{ background: tk.chart[i % 6] }" /><b>{{ m.name }}</b> <span class="mono fs-xs muted">{{ m.id }}</span></td>
              <td class="fs-sm">{{ m.where }}</td>
              <td class="fs-sm text-2" style="white-space: normal; min-width: 260px">{{ m.desc }}</td>
              <td class="mono fs-sm">{{ m.model }}</td>
              <td><span class="tag" :class="m.trigger === '自动' ? 'info' : m.trigger === '用户' ? '' : 'primary'">{{ m.trigger }}</span></td>
              <td class="r num">{{ m.calls.toLocaleString() }}</td>
              <td class="r num">{{ fmt(m.total) }}</td>
              <td><div class="row gap-4"><div class="bar grow"><i :style="{ width: `${(m.total / total) * 100}%`, background: tk.chart[i % 6] }" /></div><span class="num fs-xs" style="width: 40px; text-align: right">{{ ((m.total / total) * 100).toFixed(1) }}%</span></div></td>
              <td class="r num">{{ m.cost.toFixed(1) }} 元</td>
            </tr>
          </tbody>
        </table>
      </div>
      <template #footer>「自动」模块由后端定时任务或告警触发，不经用户发起；模型可在系统设置 · AI 中按模块切换</template>
    </Panel>

    <Panel title="最近调用" code="AI_CALLS" :icon="PhoneCall" flush>
      <div class="table-wrap" style="border-top: 0; max-height: 360px">
        <table class="table">
          <thead><tr><th>时间</th><th>调用 ID</th><th>模块</th><th>发起人</th><th class="r">输入</th><th class="r">输出</th><th class="r">耗时</th><th>结果</th></tr></thead>
          <tbody>
            <tr v-for="c in calls" :key="c.id">
              <td class="num fs-sm">{{ dt(c.time) }}</td>
              <td class="mono fs-xs">{{ c.id }}</td>
              <td>{{ nameOf(c.module) }}</td>
              <td class="fs-sm">{{ c.user }}</td>
              <td class="r num">{{ c.input.toLocaleString() }}</td>
              <td class="r num">{{ c.output.toLocaleString() }}</td>
              <td class="r num">{{ (c.latency / 1000).toFixed(1) }} s</td>
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
