<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Thermometer, WifiOff, X } from 'lucide-vue-next'
import EChart from './EChart.vue'
import StatusTag from './StatusTag.vue'
import { api } from '@/api/http'
import { useLiveStore } from '@/stores/live'
import { useOverviewStore } from '@/stores/overview'
import { useTokens } from '@/composables/useTokens'
import { PHASE_TEXT, plans } from '@/mock/cluster'

const id = defineModel<string | null>({ default: null })
const live = useLiveStore()
const overview = useOverviewStore()
const router = useRouter()
const tk = useTokens()

const fromApi = computed(() => Boolean(id.value && overview.machine(id.value)))
const m = computed(() => (id.value ? (overview.machine(id.value) ?? live.machine(id.value)) : undefined))
const plan = computed(() => plans.find((p) => p.plan_id === m.value?.plan_id))
const slotIdx = ref(1)
const curve = ref<{ points: { t_s: number; T0: number; T1: number; Ta: number }[]; deltas: Record<string, number> } | null>(null)
watch(id, () => {
  const s = m.value?.slots.find((x) => x.phase === 'SAMPLING')
  slotIdx.value = s?.index ?? m.value?.slots[0]?.index ?? 1
})
const slot = computed(() => m.value?.slots.find((s) => s.index === slotIdx.value))
const rcText = computed(() => {
  const fromCurve = curve.value?.deltas?.Rc
  if (fromCurve != null) return Number(fromCurve).toFixed(3)
  const s = slot.value
  if (!s || s.power_w <= 0) return '—'
  return ((s.t1 - s.ta) / s.power_w).toFixed(3)
})
watch([id, slotIdx, fromApi], async () => {
  curve.value = null
  if (!fromApi.value || !id.value) return
  try {
    curve.value = await api(`/machines/${id.value}/slots/${slotIdx.value}/curve`)
  } catch {
    curve.value = { points: [], deltas: {} }
  }
})

/** 运行总览走后端曲线；其它页面仍用本地推演。 */
const curveOpt = computed(() => {
  const t = tk.value
  const s = slot.value
  const p = plan.value
  if (fromApi.value) {
    const points = curve.value?.points ?? []
    if (!points.length) return {}
    return {
      grid: { left: 40, right: 12, top: 28, bottom: 24 },
      legend: { data: ['T0 加热块', 'T1 板面', 'Ta 房间'] },
      xAxis: { type: 'category', data: points.map((row) => `${row.t_s}s`), boundaryGap: false },
      yAxis: { type: 'value', name: '℃', scale: true },
      series: [
        { name: 'T0 加热块', type: 'line', data: points.map((row) => row.T0), showSymbol: false, lineStyle: { width: 2, color: t.danger }, itemStyle: { color: t.danger } },
        { name: 'T1 板面', type: 'line', data: points.map((row) => row.T1), showSymbol: false, lineStyle: { width: 2, color: t.chart[0] }, itemStyle: { color: t.chart[0] } },
        { name: 'Ta 房间', type: 'line', data: points.map((row) => row.Ta), showSymbol: false, lineStyle: { width: 1, type: 'dashed', color: t['text-3'] }, itemStyle: { color: t['text-3'] } },
      ],
    }
  }
  if (!s || !p) return {}
  const n = Math.max(2, Math.round((s.progress / 100) * p.duration_s))
  const xs = Array.from({ length: n }, (_, i) => i)
  const k = (i: number) => 1 - Math.exp(-((i / p.duration_s) * 100) / 28)
  const t1 = xs.map((i) => +(s.ta + (s.t1 - s.ta) / Math.max(0.01, k(n - 1)) * k(i)).toFixed(2))
  const t0 = xs.map((i, j) => +(t1[j] + (s.t0 - s.t1) * (0.4 + 0.6 * k(i)) / Math.max(0.01, 0.4 + 0.6 * k(n - 1))).toFixed(2))
  return {
    grid: { left: 40, right: 12, top: 28, bottom: 24 },
    legend: { data: ['T0 加热块', 'T1 板面', 'Ta 房间'] },
    xAxis: { type: 'category', data: xs.map((x) => `${x}s`), boundaryGap: false, axisLabel: { interval: Math.ceil(n / 6) } },
    yAxis: { type: 'value', name: '℃', scale: true },
    series: [
      { name: 'T0 加热块', type: 'line', data: t0, showSymbol: false, lineStyle: { width: 2, color: t.danger }, itemStyle: { color: t.danger } },
      { name: 'T1 板面', type: 'line', data: t1, showSymbol: false, lineStyle: { width: 2, color: t.chart[0] }, itemStyle: { color: t.chart[0] } },
      { name: 'Ta 房间', type: 'line', data: xs.map(() => +s.ta.toFixed(2)), showSymbol: false, lineStyle: { width: 1, type: 'dashed', color: t['text-3'] }, itemStyle: { color: t['text-3'] } },
    ],
  }
})
const phaseCls = (p: string) => (p === 'ERROR' ? 'danger' : p === 'SAMPLING' ? 'primary' : p === 'IDLE' ? '' : 'info')
const close = () => (id.value = null)
const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close()
watch(id, (v) => (v ? window.addEventListener('keydown', onKey) : window.removeEventListener('keydown', onKey)))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Transition name="dr">
    <div v-if="m" class="mask" @mousedown.self="close">
      <aside class="drawer" role="dialog" :aria-label="`${m.machine_id} 详情`" tabindex="-1">
        <header class="hd">
          <div class="col gap-4 grow">
            <div class="row">
              <h2 class="mono">{{ m.machine_id }}</h2>
              <StatusTag :status="m.comm_status === 'DISCONNECTED' ? 'DISCONNECTED' : m.status" />
              <StatusTag v-if="m.comm_status === 'DEGRADED'" status="DEGRADED" :text="`降级 · ${m.comm_note}`" />
            </div>
            <span class="fs-sm muted">{{ m.serial }} · 夹具 {{ m.fixture }} · {{ m.plc }} · {{ m.firmware }}</span>
          </div>
          <button class="btn btn-sm" @click="router.push({ path: '/devices', query: { m: m.machine_id } }); close()">设备配置<ArrowRight :size="14" /></button>
          <button class="btn btn-ghost btn-icon" v-tip="{ text: '关闭', kbd: 'Esc' }" @click="close"><X :size="18" /></button>
        </header>

        <div v-if="m.comm_status === 'DISCONNECTED'" class="dis">
          <WifiOff :size="26" />
          <b>通信断开，无法读取实时状态</b>
          <span class="fs-sm muted">集群对该机台的状态查询与指令都会返回 503；测试答案与故障通道仍可用。下方为断开前最后一次同步的数据。</span>
        </div>

        <div class="strip">
          <div><span>测试方案</span><b>{{ plan ? `${plan.name} · v${m.plan_version}` : (m.plan_id ? `${m.plan_id} · v${m.plan_version ?? ''}` : '未下发') }}</b></div>
          <div><span>房间温度</span><b class="num">{{ m.room_temp_c.toFixed(2) }} ℃</b></div>
          <div><span>仿真倍率</span><b class="num">×{{ m.speed }}</b></div>
          <div><span>报警</span><b :class="{ 't-danger': m.alarm }">{{ m.alarm || '无' }}</b></div>
        </div>

        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>槽位</th><th>步骤</th><th>均热板序列号</th><th style="width: 110px">采样进度</th><th class="r">T0</th><th class="r">T1</th><th class="r">真空 kPa</th><th class="r">已测</th></tr></thead>
            <tbody>
              <tr v-for="s in m.slots" :key="s.index" class="clickable" :class="{ 'is-selected': s.index === slotIdx }" @click="slotIdx = s.index">
                <td class="mono fw-6">#{{ s.index }}</td>
                <td><span class="tag" :class="phaseCls(s.phase)">{{ PHASE_TEXT[s.phase] }}</span></td>
                <td class="mono fs-xs">{{ s.serial_number ?? '—' }}</td>
                <td><div v-if="s.phase === 'SAMPLING'" class="bar"><i :style="{ width: `${s.progress}%` }" /></div><span v-else class="muted fs-xs">{{ s.last_error || '—' }}</span></td>
                <td class="r num">{{ s.t0.toFixed(2) }}</td>
                <td class="r num">{{ s.t1.toFixed(2) }}</td>
                <td class="r num" :class="{ 't-danger': s.vacuum_kpa > -60 && ['CLAMPING', 'SAMPLING'].includes(s.phase) }">{{ s.vacuum_kpa.toFixed(1) }}</td>
                <td class="r num muted">{{ s.tests_done }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <section v-if="slot" class="curve">
          <div class="row-between">
            <span class="row gap-4 fw-6"><Thermometer :size="15" />槽位 #{{ slot.index }} 过程曲线</span>
            <span class="fs-xs muted mono">{{ slot.run_id ?? '无进行中的测试' }}</span>
          </div>
          <div class="kv-row">
            <span>Temp_T0-T1 <b class="num">{{ Number(curve?.deltas?.['Temp_T0-T1'] ?? (slot.t0 - slot.t1)).toFixed(3) }} ℃</b></span>
            <span>Rc <b class="num">{{ rcText }} ℃/W</b></span>
            <span>power_w <b class="num">{{ slot.power_w.toFixed(3) }} W</b></span>
          </div>
          <EChart v-if="fromApi ? curve?.points?.length : slot.phase === 'SAMPLING'" :option="curveOpt" :height="220" />
          <div v-else class="empty-c fs-sm muted">{{ fromApi ? '这条测试还没有过程曲线' : `当前步骤为「${PHASE_TEXT[slot.phase]}」，进入采样后显示曲线` }}</div>
        </section>
      </aside>
    </div>
  </Transition>
</template>

<style scoped>
.mask { position: fixed; inset: 0; z-index: 80; background: rgba(12, 16, 20, 0.28); display: flex; justify-content: flex-end; }
.drawer { width: min(820px, 92vw); height: 100%; overflow: auto; background: var(--c-surface); border-left: 3px solid var(--c-accent); box-shadow: var(--shadow-pop); display: flex; flex-direction: column; outline: none; }
.hd { display: flex; align-items: center; gap: 8px; padding: 14px 14px 12px 16px; border-bottom: var(--bw) solid var(--c-border); }
.hd h2 { font-size: var(--fs-xl); }
.dis { margin: 12px 16px 0; padding: 14px; display: flex; flex-direction: column; gap: 6px; align-items: flex-start; color: var(--c-danger); background: repeating-linear-gradient(-45deg, var(--c-danger-weak) 0 8px, var(--c-surface) 8px 16px); border: var(--bw) solid var(--c-danger); }
.strip { display: grid; grid-template-columns: 2fr 1fr 1fr 2fr; gap: 1px; margin: 12px 16px; background: var(--c-border); border: var(--bw) solid var(--c-border); }
.strip > div { background: var(--c-surface-2); padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.strip span { font-size: var(--fs-xs); color: var(--c-text-3); }
.strip b { font-size: var(--fs-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.table-wrap { margin: 0 16px; border: var(--bw) solid var(--c-border); }
.curve { margin: 12px 16px 16px; padding: 12px; border: var(--bw) solid var(--c-border); display: flex; flex-direction: column; gap: 8px; }
.kv-row { display: flex; gap: 18px; font-size: var(--fs-sm); color: var(--c-text-2); }
.empty-c { height: 120px; display: grid; place-items: center; background: var(--c-surface-2); }
.dr-enter-active, .dr-leave-active { transition: opacity 160ms var(--ease); }
.dr-enter-active .drawer, .dr-leave-active .drawer { transition: transform 200ms var(--ease); }
.dr-enter-from, .dr-leave-to { opacity: 0; }
.dr-enter-from .drawer, .dr-leave-to .drawer { transform: translateX(40px); }
</style>
