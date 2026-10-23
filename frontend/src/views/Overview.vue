<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Activity, ArrowRight, BellRing, ClipboardCheck, Cpu, Download, Gauge, Microscope, Pause, Play, Server, Sigma, Table2, TrendingUp, TriangleAlert,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import PipelineBar from '@/components/PipelineBar.vue'
import Kpi from '@/components/Kpi.vue'
import Panel from '@/components/Panel.vue'
import EChart from '@/components/EChart.vue'
import StatusTag from '@/components/StatusTag.vue'
import MachineDrawer from '@/components/MachineDrawer.vue'
import { useOverviewStore, type MachineView } from '@/stores/overview'
import { useAppStore } from '@/stores/app'
import { useTokens } from '@/composables/useTokens'
import { PHASE_TEXT } from '@/mock/cluster'
import { hms } from '@/utils/format'

const ov = useOverviewStore()
const app = useAppStore()
const router = useRouter()
const route = useRoute()
const tk = useTokens()
ov.start()

const drawer = ref<string | null>((route.query.m as string) || null)

const aggs = computed(() => ov.agg)

const planName = (m: MachineView) => (m.plan_id ? `${m.plan_id}${m.plan_version ? ` · v${m.plan_version}` : ''}` : '未下发方案')
const cardState = (m: MachineView) => (m.comm_status === 'DISCONNECTED' ? 'dis' : m.status === 'FAULT' ? 'fault' : m.status === 'MAINTENANCE' ? 'maint' : m.slots.some((s) => s.phase === 'ERROR') ? 'warn' : 'ok')
const cellCls = (p: string) => ({ ERROR: 'err', SAMPLING: 'smp', IDLE: 'idle', COMPLETED: 'idle' } as Record<string, string>)[p] ?? 'mv'

/* ---------- 图表 ---------- */
const label = (ts: number) => hms(ts).slice(0, 5)
const testsDelta = computed(() => (ov.kpi.prevTests ? +(((ov.kpi.tests - ov.kpi.prevTests) / ov.kpi.prevTests) * 100).toFixed(1) : undefined))
const yieldDelta = computed(() => (ov.kpi.prevTests ? +(ov.kpi.yieldRate - ov.kpi.prevYield).toFixed(2) : undefined))

const yieldOpt = computed(() => {
  const t = tk.value
  const a = aggs.value
  return {
    grid: { left: 40, right: 44, top: 30, bottom: 24 },
    legend: { data: ['通过', '不合格', '中止', '良率'] },
    xAxis: { type: 'category', data: a.map((x) => label(x.bucket)), axisLabel: { interval: Math.ceil(a.length / 10) } },
    yAxis: [{ type: 'value', name: '片 / 5min' }, { type: 'value', name: '%', min: 0, max: 100, splitLine: { show: false } }],
    series: [
      { name: '通过', type: 'bar', stack: 'n', data: a.map((x) => x.passed), itemStyle: { color: t['border-strong'] }, barWidth: '60%' },
      { name: '不合格', type: 'bar', stack: 'n', data: a.map((x) => x.failed), itemStyle: { color: t.danger } },
      { name: '中止', type: 'bar', stack: 'n', data: a.map((x) => x.aborted), itemStyle: { color: t.warn } },
      {
        name: '良率', type: 'line', yAxisIndex: 1, data: a.map((x) => +((x.passed / Math.max(1, x.tests)) * 100).toFixed(2)), showSymbol: false, smooth: 0.2,
        lineStyle: { width: 2, color: t.primary }, itemStyle: { color: t.primary },
        markLine: { symbol: 'none', silent: true, data: [{ yAxis: 97 }], lineStyle: { color: t.warn, type: 'dashed' }, label: { formatter: '目标 97%', color: t.warn, fontSize: 10 } },
      },
    ],
  }
})

const anomalyOpt = computed(() => {
  const t = tk.value
  const hours = ov.anomaly.hours.map((ts) => hms(ts).slice(0, 5))
  const series = ov.anomaly.series
  return {
    grid: { left: 32, right: 8, top: 30, bottom: 24 },
    legend: { data: ['设备异常', '产品缺陷', '通信', '数据异常'] },
    xAxis: { type: 'category', data: hours },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      { name: '设备异常', type: 'bar', stack: 'a', data: series.equipment ?? [], itemStyle: { color: t.danger }, barWidth: '55%' },
      { name: '产品缺陷', type: 'bar', stack: 'a', data: series.product ?? [], itemStyle: { color: t.chart[0] } },
      { name: '通信', type: 'bar', stack: 'a', data: series.communication ?? [], itemStyle: { color: t.warn } },
      { name: '数据异常', type: 'bar', stack: 'a', data: series.data ?? [], itemStyle: { color: t['text-3'] } },
    ],
  }
})

const rcOpt = computed(() => {
  const t = tk.value
  const items = ov.rc.items
  return {
    grid: { left: 44, right: 12, top: 14, bottom: 24 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(3)} ℃/W` },
    xAxis: { type: 'category', data: items.map((item) => item.machine_id), axisLabel: { interval: 0 } },
    yAxis: { type: 'value', scale: true, axisLabel: { formatter: (v: number) => v.toFixed(2) } },
    series: [{
      type: 'bar', barWidth: '55%',
      data: items.map((item) => ({ value: item.bias, itemStyle: { color: Math.abs(item.bias) > 0.06 ? t.danger : Math.abs(item.bias) > 0.03 ? t.warn : t.chart[0] } })),
      markLine: { symbol: 'none', silent: true, data: [{ yAxis: 0 }], lineStyle: { color: t['text-3'] } },
    }],
  }
})

const recent5 = computed(() => [...ov.agg].slice(-8).reverse())

/* ---------- 告警 ---------- */
const levelKind = { critical: 'danger', major: 'warn', minor: 'info' } as const
const levelText = { critical: '严重', major: '主要', minor: '次要' }
const alarmFilter = ref<'open' | 'all'>('open')
const alarmList = computed(() => ov.alarms.filter((a) => alarmFilter.value === 'all' || !a.acked).slice(0, 12))
const pipeStats = computed(() => ov.pipe)

function exportCsv() {
  app.toast({ kind: 'ok', title: '已导出 5 分钟汇总', desc: `agg_5m_${new Date().toISOString().slice(0, 10)}.csv` })
}
</script>

<template>
  <div class="page">
    <PageHeader title="运行总览" :desc="`${ov.machines.length} 台在册机台 · 数据来自后端数据库`">
      <div class="seg" role="group" aria-label="时间范围">
        <button :aria-pressed="ov.range === '2h'" @click="ov.range = '2h'; ov.refresh()">近 2 小时</button>
        <button :aria-pressed="ov.range === '8h'" @click="ov.range = '8h'; ov.refresh()">本班 8 小时</button>
      </div>
      <button class="btn btn-icon" :aria-pressed="ov.paused" v-tip="ov.paused ? '恢复实时刷新' : '暂停实时刷新（便于读数）'" @click="ov.paused = !ov.paused">
        <Play v-if="ov.paused" :size="16" /><Pause v-else :size="16" />
      </button>
      <button class="btn" @click="exportCsv"><Download :size="16" />导出</button>
    </PageHeader>

    <PipelineBar :stats="pipeStats" />

    <div class="grid g-6">
      <Kpi label="在线机台" :value="`${ov.kpi.online}/${ov.kpi.total}`" :icon="Server" :sub="`故障 ${ov.machines.filter((m) => m.status === 'FAULT').length} · 维修 ${ov.machines.filter((m) => m.status === 'MAINTENANCE').length} · 断开 ${ov.machines.filter((m) => m.comm_status === 'DISCONNECTED').length}`" :state="ov.kpi.online < ov.kpi.total ? 'warn' : 'ok'" />
      <Kpi label="工作槽位" :value="`${ov.kpi.busy}/${ov.kpi.slotTotal}`" :icon="Cpu" :sub="`ERROR 槽位 ${ov.kpi.err}`" :state="ov.kpi.err ? 'warn' : 'ok'" />
      <Kpi label="本班测试" :value="ov.kpi.tests.toLocaleString()" unit="片" :icon="Activity" :delta="testsDelta" delta-unit="%" higher-is-better sub="较上一班" />
      <Kpi label="良率" :value="ov.kpi.yieldRate.toFixed(2)" unit="%" :icon="TrendingUp" :delta="yieldDelta" delta-unit="%" higher-is-better sub="目标 ≥ 97%" :state="ov.kpi.yieldRate >= 97 ? 'ok' : 'warn'" />
      <Kpi label="平均 Rc" :value="ov.kpi.rc.toFixed(3)" unit="℃/W" :icon="Gauge" sub="近 120 片 · (T1−Ta)/功率" />
      <Kpi label="未确认告警" :value="ov.kpi.openAlarms" unit="条" :icon="BellRing" :sub="`严重 ${ov.kpi.critical}`" :state="ov.kpi.critical ? 'danger' : ov.kpi.openAlarms ? 'warn' : 'ok'" />
    </div>

    <p v-if="ov.error" class="fs-sm t-danger" style="margin: 0">{{ ov.error }}</p>
    <Panel title="机台状态" code="FLEET" :icon="Server">
      <template #actions>
        <span class="legend">
          <span><i class="lg smp" />采样</span><span><i class="lg mv" />复位 / 预热 / 上料 / 夹紧 / 恢复</span><span><i class="lg idle" />空闲</span><span><i class="lg err" />ERROR</span>
        </span>
      </template>
      <div class="wall">
        <button v-for="m in ov.machines" :key="m.machine_id" class="mc" :class="cardState(m)" @click="drawer = m.machine_id">
          <div class="row-between">
            <b class="mono mid">{{ m.machine_id }}</b>
            <StatusTag :status="m.comm_status === 'DISCONNECTED' ? 'DISCONNECTED' : m.status" />
          </div>
          <div class="fs-xs muted ellipsis">{{ planName(m) }}</div>
          <div class="cells" :style="{ gridTemplateColumns: `repeat(${m.slot_count || 1}, 1fr)` }" :aria-label="`${m.slot_count} 个槽位`">
            <i v-for="s in m.slots" :key="s.index" :class="cellCls(s.phase)" v-tip="`#${s.index} ${PHASE_TEXT[s.phase]}${s.last_error ? ' · ' + s.last_error : ''}`">
              <span v-if="s.phase === 'SAMPLING'" :style="{ height: `${s.progress}%` }" />
            </i>
          </div>
          <div class="row-between fs-xs">
            <span class="num muted">{{ m.room_temp_c.toFixed(1) }} ℃</span>
            <span v-if="m.alarm" class="t-danger ellipsis">{{ m.alarm.split(' · ')[0] }}</span>
            <span v-else-if="m.comm_status === 'DEGRADED'" class="t-warn">{{ m.comm_note }}</span>
            <span v-else class="num">
              良率 <b>{{ m.yield_recent?.n ? ((m.yield_recent.passed / m.yield_recent.n) * 100).toFixed(1) : '—' }}%</b>
            </span>
          </div>
        </button>
      </div>
    </Panel>

    <div class="grid g-3">
      <Panel class="span-2" title="产出与良率" code="5-MIN BUCKETS" :icon="TrendingUp">
        <EChart :option="yieldOpt" :height="270" />
      </Panel>

      <Panel title="告警" code="ALARM" :icon="BellRing" flush>
        <template #actions>
          <div class="seg sm">
            <button :aria-pressed="alarmFilter === 'open'" @click="alarmFilter = 'open'">未确认 {{ ov.kpi.openAlarms }}</button>
            <button :aria-pressed="alarmFilter === 'all'" @click="alarmFilter = 'all'">全部</button>
          </div>
        </template>
        <ul class="alarms">
          <li v-for="a in alarmList" :key="a.id" :class="[levelKind[a.level], { acked: a.acked }]">
            <span class="tag" :class="levelKind[a.level]">{{ levelText[a.level] }}</span>
            <div class="grow" style="min-width: 0">
              <div class="row-between">
                <b class="mono fs-sm">{{ a.machine_id }}{{ a.slot_index ? `#${a.slot_index}` : '' }} <span class="muted fw-6">· {{ a.code }}</span></b>
                <span class="fs-xs muted num">{{ hms(a.time) }}</span>
              </div>
              <p class="fs-sm ellipsis text-2" :title="a.message">{{ a.message }}</p>
            </div>
            <button class="btn btn-sm btn-icon" v-tip="'交给 Agent 归因'" @click="router.push({ path: '/agent', query: { q: `分析 ${a.machine_id} 告警 ${a.code} 的原因` } })"><Microscope :size="14" /></button>
            <button
              v-if="!a.acked"
              class="btn btn-sm btn-icon"
              v-tip="'确认告警'"
              @click="ov.ack(a.id); app.toast({ kind: 'ok', title: `${a.id} 已确认`, action: { label: '撤销', run: () => ov.unack(a.id) } })"
            >
              <ClipboardCheck :size="14" />
            </button>
          </li>
          <li v-if="!alarmList.length" class="none">没有未确认的告警</li>
        </ul>
      </Panel>
    </div>

    <div class="grid g-3">
      <Panel title="异常趋势" code="BY CATEGORY · 1H" :icon="TriangleAlert">
        <EChart :option="anomalyOpt" :height="220" />
      </Panel>
      <Panel title="5 分钟汇总" code="AGG_5M" :icon="Table2" flush>
        <div class="table-wrap" style="border-top: 0; max-height: 262px">
          <table class="table">
            <thead><tr><th>时间窗</th><th class="r">测试</th><th class="r">不合格</th><th class="r">良率</th><th class="r">Rc 均值</th><th class="r">T0−T1</th></tr></thead>
            <tbody>
              <tr v-for="r in recent5" :key="r.bucket">
                <td class="num fs-sm">{{ label(r.bucket) }}–{{ label(r.bucket + 300_000) }}</td>
                <td class="r num">{{ r.tests }}</td>
                <td class="r num" :class="{ 't-danger fw-6': r.failed > 2 }">{{ r.failed }}</td>
                <td class="r num">{{ ((r.passed / Math.max(1, r.tests)) * 100).toFixed(1) }}%</td>
                <td class="r num">{{ r.rc_mean.toFixed(3) }}</td>
                <td class="r num">{{ r.dt01_mean.toFixed(2) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="机台 Rc 偏差" code="VS 全线中位数" :icon="Sigma">
        <template #actions>
          <button class="btn btn-ghost btn-sm" @click="router.push('/devices')">一致性<ArrowRight :size="14" /></button>
        </template>
        <EChart :option="rcOpt" :height="220" />
      </Panel>
    </div>

    <MachineDrawer v-model="drawer" />
  </div>
</template>

<style scoped>
.legend { display: flex; gap: 12px; font-size: var(--fs-xs); color: var(--c-text-3); }
.legend span { display: inline-flex; align-items: center; gap: 4px; }
.lg { width: 10px; height: 10px; display: inline-block; border: var(--bw) solid var(--c-border-strong); }
.lg.smp, .cells i.smp { background: var(--c-primary-weak); border-color: var(--c-primary); }
.lg.mv, .cells i.mv { background: var(--c-info-weak); border-color: var(--c-info); }
.lg.idle, .cells i.idle { background: var(--c-surface-3); }
.lg.err, .cells i.err { background: var(--c-danger); border-color: var(--c-danger); }

.wall { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; }
@media (max-width: 1440px) { .wall { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
.mc {
  --_c: var(--c-ok);
  display: flex; flex-direction: column; gap: 6px;
  padding: 8px 10px 8px 12px; text-align: left;
  background: var(--c-surface-2); border: var(--bw) solid var(--c-border);
  box-shadow: inset 3px 0 0 var(--_c);
  cursor: pointer; min-width: 0;
}
.mc:hover { border-color: var(--c-text-2); background: var(--c-surface); }
.mc.warn { --_c: var(--c-warn); }
.mc.fault { --_c: var(--c-danger); background: var(--c-danger-weak); }
.mc.maint { --_c: var(--c-info); }
.mc.dis { --_c: var(--c-danger); background: repeating-linear-gradient(-45deg, var(--c-surface-3) 0 6px, var(--c-surface-2) 6px 12px); }
.mc.dis .cells { opacity: 0.35; }
.mid { font-size: var(--fs-lg); }
.cells { display: grid; grid-template-columns: repeat(10, 1fr); gap: 3px; }
.cells i { position: relative; height: 18px; border: var(--bw) solid var(--c-border-strong); overflow: hidden; }
.cells i span { position: absolute; left: 0; right: 0; bottom: 0; background: var(--c-primary); opacity: 0.55; transition: height 400ms var(--ease); }

.alarms { list-style: none; margin: 0; padding: 0; max-height: 298px; overflow: auto; }
.alarms li { display: flex; align-items: center; gap: 8px; padding: 8px 10px 8px 12px; border-bottom: var(--bw) solid var(--c-border); box-shadow: inset 3px 0 0 var(--c-info); }
.alarms li.danger { box-shadow: inset 3px 0 0 var(--c-danger); }
.alarms li.warn { box-shadow: inset 3px 0 0 var(--c-warn); }
.alarms li.acked { opacity: 0.55; }
.alarms .none { justify-content: center; color: var(--c-text-3); padding: 32px; box-shadow: none; }
</style>
