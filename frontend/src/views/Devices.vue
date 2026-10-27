<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Bot, CircleAlert, Cpu, Crosshair, FileClock, History, Microscope, Plus, Power, PowerOff, RotateCcw, Search, SlidersHorizontal, Unplug, Wrench,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Panel from '@/components/Panel.vue'
import EChart from '@/components/EChart.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api } from '@/api/http'
import type { Alarm, Machine } from '@/api/types'
import { useAppStore } from '@/stores/app'
import { useTokens } from '@/composables/useTokens'
import { PHASE_TEXT, TEMP_CHANNELS } from '@/mock/cluster'
import { ago, dt } from '@/utils/format'

interface DeviceMachine extends Machine { last_sync_at: number }
interface BiasItem { channel: string; value: number }
interface CompItem { channel: string; value: number }
interface CompWrite { time: number; actor: string; mode: string; compensation: CompItem[]; audit_id: string }
interface Suggestion { channel: string; value: number; reason: string }
interface DriftRow { drift_id: string; channel: string; kind: string; value: number; current: number }
interface Suggestion { channel: string; value: number; reason: string }
interface DriftRow { drift_id: string; channel: string; kind: string; value: number; current: number }
interface PlanUse { plan_id: string; name: string; version: number; from: number; to: number | null; runs: number }

const app = useAppStore()
const route = useRoute()
const router = useRouter()
const tk = useTokens()

const machines = ref<DeviceMachine[]>([])
const cur = ref(String(route.query.m || ''))
const kw = ref('')
const tab = ref<'info' | 'calib' | 'alarm' | 'plans'>((route.query.tab as 'info') || 'calib')
const TABS = [
  { k: 'info', label: '配置与槽位', icon: Cpu },
  { k: 'calib', label: '一致性与补偿', icon: Crosshair },
  { k: 'alarm', label: '异常记录', icon: CircleAlert },
  { k: 'plans', label: '方案记录', icon: FileClock },
] as const

const m = computed(() => machines.value.find((item) => item.machine_id === cur.value))
const dis = computed(() => m.value?.comm_status === 'DISCONNECTED')
const shown = computed(() => machines.value.filter((item) => item.machine_id.toLowerCase().includes(kw.value.toLowerCase())))
watch(cur, (id) => { if (id) router.replace({ query: { ...route.query, m: id } }) })

const bias = ref<BiasItem[]>([])
const threshold = ref(0.15)
const rcItems = ref<{ machine_id: string; bias: number }[]>([])
const comp = ref<CompItem[]>([])
const savedComp = ref<CompItem[]>([])
const history = ref<CompWrite[]>([])
const suggest = ref<Suggestion[]>([])
const drifts = ref<DriftRow[]>([])
const driftsSupported = ref(true)
const sectionError = ref<Record<string, string>>({})

function reasonOf(err: unknown) {
  return err instanceof Error && err.message ? err.message : '请求失败'
}

async function loadSection<T>(id: string, key: string, run: () => Promise<T>, empty: T): Promise<T> {
  try {
    const value = await run()
    if (cur.value === id) sectionError.value[key] = ''
    return value
  } catch (err) {
    if (cur.value === id) sectionError.value[key] = reasonOf(err)
    return empty
  }
}
const alarms = ref<Alarm[]>([])
const plans = ref<PlanUse[]>([])
const mode = ref<'add' | 'set'>('add')
const newCh = ref('T1')
const newVal = ref<number | null>(null)
const LV = { critical: ['danger', '严重'], major: ['warn', '主要'], minor: ['info', '次要'] } as const

async function loadMachines() {
  machines.value = await api<DeviceMachine[]>('/machines')
  if (!machines.value.some((item) => item.machine_id === cur.value)) cur.value = machines.value[0]?.machine_id ?? ''
}

async function loadDetail() {
  const id = cur.value
  if (!id) return
  sectionError.value = {}
  const [alarmPage, historyPage, planPage, rc] = await Promise.all([
    api<{ items: Alarm[] }>(`/alarms?machine_id=${id}&limit=100`),
    api<{ items: PlanUse[] }>(`/machines/${id}/plan-history`),
    loadSection(id, 'history', () => api<{ items: CompWrite[] }>(`/machines/${id}/compensation/history`), { items: [] }),
    loadSection(id, 'rc', () => api<{ items: { machine_id: string; bias: number }[] }>('/stats/rc-bias'), { items: [] }),
  ])
  if (cur.value !== id) return
  alarms.value = alarmPage.items
  plans.value = historyPage.items
  history.value = planPage.items
  rcItems.value = rc.items
  const [biasPage, suggestionPage, driftPage] = await Promise.all([
    loadSection(id, 'bias', () => api<{ items: BiasItem[]; threshold_c: number }>(`/machines/${id}/channel-bias`), { items: [], threshold_c: 0.15 }),
    loadSection(id, 'suggest', () => api<{ items: Suggestion[] }>(`/machines/${id}/compensation/suggestion`), { items: [] }),
    loadSection(id, 'drifts', () => api<{ items: DriftRow[]; supported: boolean }>(`/machines/${id}/drifts`), { items: [], supported: false }),
  ])
  if (cur.value !== id) return
  bias.value = biasPage.items
  threshold.value = biasPage.threshold_c
  suggest.value = suggestionPage.items
  drifts.value = driftPage.items
  driftsSupported.value = driftPage.supported
  if (m.value?.comm_status === 'DISCONNECTED') {
    comp.value = []
    savedComp.value = []
    return
  }
  const current = await loadSection(id, 'comp', () => api<{ items: CompItem[] }>(`/machines/${id}/compensation`), { items: [] })
  if (cur.value !== id) return
  comp.value = current.items.map((item) => ({ ...item }))
  savedComp.value = current.items.map((item) => ({ ...item }))
}

watch(cur, () => { loadDetail() })
let timer = 0
onMounted(async () => {
  await loadMachines()
  await loadDetail()
  timer = window.setInterval(loadMachines, 5000)
})
onUnmounted(() => window.clearInterval(timer))

async function op(kind: 'power-on' | 'power-off' | 'maintenance' | 'reset') {
  if (!m.value) return
  const text = { 'power-on': '上电', 'power-off': '关机', maintenance: m.value.status === 'MAINTENANCE' ? '结束维修' : '进入维修', reset: '复位' }[kind]
  const busy = m.value.slots.some((slot) => slot.phase === 'SAMPLING')
  const ok = await app.confirm({
    title: `${cur.value} · ${text}`,
    desc: busy && (kind === 'power-off' || kind === 'maintenance') ? '有槽位正在采样，这些测试会记为中止。' : `对 ${cur.value} 执行${text}。`,
    danger: kind === 'power-off' || (busy && kind === 'maintenance'),
    confirmText: text,
    typeToConfirm: kind === 'power-off' && busy ? cur.value : undefined,
  })
  if (!ok) return
  try {
    const body = kind === 'maintenance' ? JSON.stringify({ on: m.value.status !== 'MAINTENANCE' }) : undefined
    await api(`/machines/${cur.value}/${kind}`, { method: 'POST', body, headers: { 'Idempotency-Key': crypto.randomUUID() } })
    await loadMachines()
    app.toast({ kind: 'ok', title: `${cur.value} 已${text}` })
  } catch (err) {
    app.toast({ kind: 'danger', title: `${text}没有执行`, desc: err instanceof Error ? err.message : '' })
  }
}

const biasOpt = computed(() => {
  const t = tk.value
  if (!bias.value.length) return null
  const lim = threshold.value
  return {
    grid: { left: 44, right: 12, top: 14, bottom: 24 },
    xAxis: { type: 'category', data: bias.value.map((item) => item.channel) },
    yAxis: { type: 'value' },
    series: [{
      type: 'bar', barWidth: '55%',
      data: bias.value.map((item) => ({ value: item.value, itemStyle: { color: Math.abs(item.value) > lim ? t.danger : t.chart[0] } })),
      markLine: { symbol: 'none', silent: true, lineStyle: { color: t.danger, type: 'dashed' }, data: [{ yAxis: lim }, { yAxis: -lim }] },
    }],
  }
})
const rcOf = computed(() => rcItems.value.find((item) => item.machine_id === cur.value)?.bias ?? null)
const fleetRcOpt = computed(() => {
  const t = tk.value
  return {
    grid: { left: 44, right: 12, top: 10, bottom: 24 },
    xAxis: { type: 'category', data: rcItems.value.map((item) => item.machine_id) },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', barWidth: '55%', data: rcItems.value.map((item) => ({ value: item.bias, itemStyle: { color: item.machine_id === cur.value ? t.primary : t['border-strong'] } })) }],
  }
})
const compDirty = computed(() => JSON.stringify(comp.value) !== JSON.stringify(savedComp.value))

function addComp() {
  if (newVal.value === null) return
  const found = comp.value.find((item) => item.channel === newCh.value)
  if (found) found.value = newVal.value
  else comp.value.push({ channel: newCh.value, value: newVal.value })
  newVal.value = null
}
function useSuggest() {
  mode.value = 'add'
  comp.value = suggest.value.map((item) => ({ channel: item.channel, value: item.value }))
}
async function writeComp() {
  const ok = await app.confirm({
    title: `写入 ${cur.value} 补偿`,
    desc: comp.value.map((item) => `${item.channel} ${item.value > 0 ? '+' : ''}${item.value} ℃`).join('，') || '清空补偿',
    confirmText: '写入',
    danger: true,
    typeToConfirm: cur.value,
  })
  if (!ok) return
  try {
    await api(`/machines/${cur.value}/compensation`, {
      method: 'PUT',
      body: JSON.stringify({ mode: mode.value, compensation: comp.value }),
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
    await loadDetail()
    app.toast({ kind: 'ok', title: '补偿已写入', desc: cur.value })
  } catch (err) {
    app.toast({ kind: 'danger', title: '补偿没有写入', desc: err instanceof Error ? err.message : '' })
  }
}
function channels(rows: CompItem[]) {
  return rows.map((item) => `${item.channel} ${item.value > 0 ? '+' : ''}${item.value}`).join('，') || '无'
}
</script>

<template>
  <div class="page">
    <PageHeader title="设备配置" desc="每台机台的配置、通道补偿、异常和用过的方案" />

    <div class="lay">
      <Panel flush class="side">
        <div class="pad"><div class="input-wrap" style="width: 100%"><Search :size="14" /><input v-model="kw" class="input" placeholder="机台号" aria-label="搜索机台" /></div></div>
        <ul class="mlist">
          <li v-for="item in shown" :key="item.machine_id">
            <button :class="{ on: item.machine_id === cur }" @click="cur = item.machine_id">
              <b class="mono">{{ item.machine_id }}</b>
              <span class="grow" />
              <StatusTag :status="item.comm_status === 'DISCONNECTED' ? 'DISCONNECTED' : item.status" />
            </button>
          </li>
        </ul>
      </Panel>

      <div v-if="m" class="col" style="gap: 12px; min-width: 0">
        <div class="head" :class="{ dis }">
          <div class="grow" style="min-width: 0">
            <div class="row">
              <h2 class="mono">{{ m.machine_id }}</h2>
              <StatusTag :status="m.status" />
              <StatusTag :status="m.comm_status" :text="m.comm_note ? `${m.comm_status} · ${m.comm_note}` : undefined" />
              <span v-if="m.alarm" class="tag danger">{{ m.alarm }}</span>
            </div>
            <div class="row fs-xs muted mono wrap" style="gap: 14px; margin-top: 4px">
              <span>{{ m.serial }}</span><span>夹具 {{ m.fixture }}</span><span>吸盘座 {{ m.holder }}</span><span>{{ m.plc }}</span><span>{{ m.firmware }}</span>
            </div>
          </div>
          <div class="row gap-4">
            <button class="btn btn-icon" :disabled="dis || m.status === 'READY'" v-tip="'上电'" @click="op('power-on')"><Power :size="16" /></button>
            <button class="btn btn-icon" :disabled="dis || m.status === 'OFFLINE'" v-tip="'关机'" @click="op('power-off')"><PowerOff :size="16" /></button>
            <button class="btn btn-icon" :disabled="dis" :aria-pressed="m.status === 'MAINTENANCE'" v-tip="m.status === 'MAINTENANCE' ? '结束维修' : '进入维修'" @click="op('maintenance')"><Wrench :size="16" /></button>
            <button class="btn btn-icon" :disabled="dis" v-tip="'复位'" @click="op('reset')"><RotateCcw :size="16" /></button>
          </div>
        </div>
        <div v-if="dis" class="notice">
          <Unplug :size="18" />
          <div><b>通信断开</b><p class="fs-sm">指令不会发给集群。下面是上次同步的数据{{ m.last_sync_at ? `（${ago(m.last_sync_at)}）` : '' }}。</p></div>
        </div>

        <div class="tabs" role="tablist">
          <button v-for="item in TABS" :key="item.k" role="tab" :aria-selected="tab === item.k" @click="tab = item.k">
            <component :is="item.icon" :size="14" />{{ item.label }}
            <span v-if="item.k === 'alarm'" class="tag">{{ alarms.length }}</span>
          </button>
        </div>

        <template v-if="tab === 'info'">
          <div class="grid g-4">
            <div class="kv"><span>房间温度</span><b class="num">{{ m.room_temp_c.toFixed(2) }} ℃</b></div>
            <div class="kv"><span>当前方案</span><b>{{ m.plan_id ?? '—' }} {{ m.plan_version ? `v${m.plan_version}` : '' }}</b></div>
            <div class="kv"><span>热电偶板</span><b class="mono fs-xs">{{ m.thermal_boards || '—' }}</b></div>
            <div class="kv"><span>仿真倍率</span><b class="num">×{{ m.speed }}</b></div>
          </div>
          <Panel title="能力范围" code="CAPABILITY" :icon="SlidersHorizontal">
            <div class="grid g-4 fs-sm">
              <span>时长 <b class="num">{{ m.capability.duration_low_s ?? '—' }}–{{ m.capability.duration_high_s ?? '—' }} s</b></span>
              <span>功率 <b class="num">{{ m.capability.power_low_w ?? '—' }}–{{ m.capability.power_high_w ?? '—' }} W</b></span>
              <span>压紧力 <b class="num">{{ m.capability.force_low_g ?? '—' }}–{{ m.capability.force_high_g ?? '—' }} g</b></span>
              <span>通道 <b class="num">{{ (m.capability.temp_channels ?? []).length }} 温度 · {{ (m.capability.force_channels ?? []).length }} 压力</b></span>
            </div>
          </Panel>
          <Panel title="槽位" code="SLOTS" :icon="Cpu" flush>
            <div class="table-wrap" style="border-top: 0">
              <table class="table">
                <thead><tr><th>#</th><th>步骤</th><th>序列号</th><th class="r">已测次数</th><th class="r">功率 W</th><th class="r">真空 kPa</th><th>最近错误</th></tr></thead>
                <tbody>
                  <tr v-for="slot in m.slots" :key="slot.index">
                    <td class="mono">{{ slot.index }}</td>
                    <td><span class="tag" :class="slot.phase === 'ERROR' ? 'danger' : slot.phase === 'SAMPLING' ? 'primary' : ''">{{ PHASE_TEXT[slot.phase] || slot.phase }}</span></td>
                    <td class="mono fs-xs">{{ slot.serial_number ?? '—' }}</td>
                    <td class="r num">{{ slot.tests_done.toLocaleString() }}</td>
                    <td class="r num">{{ slot.power_w.toFixed(3) }}</td>
                    <td class="r num">{{ slot.vacuum_kpa.toFixed(1) }}</td>
                    <td class="fs-sm" :class="{ 't-danger': slot.last_error }">{{ slot.last_error || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Panel>
        </template>

        <template v-else-if="tab === 'calib'">
          <div class="grid g-3">
            <Panel class="span-2" title="通道偏差" code="标准样品" :icon="Crosshair">
              <p v-if="sectionError.bias" class="fail">配置失败 · {{ sectionError.bias }}</p>
              <EChart v-else-if="biasOpt" :option="biasOpt" :height="230" />
              <p v-else class="muted">还没有这台机台的标准样品复测结果。</p>
            </Panel>
            <Panel title="Rc 偏差" code="相对全线中位数" :icon="Microscope">
              <p v-if="sectionError.rc" class="fail">配置失败 · {{ sectionError.rc }}</p>
              <template v-else>
                <div class="row" style="align-items: baseline; margin-bottom: 4px">
                  <b class="num" style="font-size: var(--fs-2xl)">{{ rcOf == null ? '—' : `${rcOf > 0 ? '+' : ''}${rcOf.toFixed(3)}` }}</b>
                  <span class="fs-sm muted">℃/W</span>
                </div>
                <EChart v-if="rcItems.length" :option="fleetRcOpt" :height="170" />
                <p v-else class="muted">还没有可比较的热阻。</p>
              </template>
            </Panel>
          </div>
          <div class="grid g-2">
            <Panel title="仿真漂移" code="GET /drifts" :icon="History" flush>
              <template #actions><span class="tag info">仅仿真</span></template>
              <div class="table-wrap" style="border-top: 0">
                <table class="table">
                  <thead><tr><th>通道</th><th>类型</th><th class="r">设定</th><th class="r">当前</th><th>判定</th></tr></thead>
                  <tbody>
                    <tr v-for="row in drifts" :key="row.drift_id || row.channel">
                      <td class="mono">{{ row.channel }}</td>
                      <td class="mono fs-sm">{{ row.kind || '—' }}</td>
                      <td class="r num">{{ row.value }}</td>
                      <td class="r num" :class="{ 't-danger fw-6': Math.abs(row.current) > threshold }">{{ row.current > 0 ? '+' : '' }}{{ row.current.toFixed(3) }} ℃</td>
                      <td><span class="tag" :class="Math.abs(row.current) > threshold ? 'danger' : 'ok'">{{ Math.abs(row.current) > threshold ? '超阈值' : '正常' }}</span></td>
                    </tr>
                    <tr v-if="sectionError.drifts"><td colspan="5" class="c fail">配置失败 · {{ sectionError.drifts }}</td></tr>
                    <tr v-else-if="!drifts.length"><td colspan="5" class="c muted" style="height: 64px">{{ driftsSupported ? '没有注入漂移' : '当前不是仿真模式，不读取注入漂移' }}</td></tr>
                  </tbody>
                </table>
              </div>
            </Panel>
            <Panel title="补偿记录" code="谁在何时改了什么" :icon="History" flush>
              <div class="table-wrap" style="border-top: 0">
                <table class="table">
                  <thead><tr><th>时间</th><th>操作者</th><th>方式</th><th>改成</th></tr></thead>
                  <tbody>
                    <tr v-for="row in history" :key="row.audit_id">
                      <td class="num fs-sm">{{ dt(row.time) }}</td>
                      <td>{{ row.actor }}</td>
                      <td class="mono">{{ row.mode }}</td>
                      <td class="fs-sm">{{ channels(row.compensation || []) }}</td>
                    </tr>
                    <tr v-if="sectionError.history"><td colspan="4" class="c fail">配置失败 · {{ sectionError.history }}</td></tr>
                    <tr v-else-if="!history.length"><td colspan="4" class="c muted" style="height: 64px">还没有从这里写入过补偿</td></tr>
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel title="通道补偿" code="PUT /compensation" :icon="SlidersHorizontal" :accent="compDirty ? 'warn' : undefined">
              <template #actions>
                <div class="seg sm">
                  <button :aria-pressed="mode === 'add'" @click="mode = 'add'">叠加</button>
                  <button :aria-pressed="mode === 'set'" @click="mode = 'set'">覆盖</button>
                </div>
              </template>
              <p v-if="sectionError.suggest" class="fail">配置失败 · {{ sectionError.suggest }}</p>
              <p v-if="sectionError.comp" class="fail">配置失败 · {{ sectionError.comp }}</p>
              <div v-if="suggest.length" class="sug">
                <Bot :size="14" />
                <span class="grow fs-sm">{{ suggest.map((item) => `${item.channel} ${item.value > 0 ? '+' : ''}${item.value}（${item.reason}）`).join('；') }}</span>
                <button class="btn btn-sm" @click="useSuggest">填入</button>
              </div>
              <table class="table">
                <thead><tr><th>通道</th><th class="r">补偿值 ℃</th><th style="width: 40px" /></tr></thead>
                <tbody>
                  <tr v-for="(item, index) in comp" :key="item.channel">
                    <td class="mono">{{ item.channel }}</td>
                    <td class="r"><input v-model.number="item.value" class="input num cell" type="number" step="0.01" :aria-label="`${item.channel} 补偿`" /></td>
                    <td><button class="btn btn-ghost btn-icon btn-sm" @click="comp.splice(index, 1)">×</button></td>
                  </tr>
                  <tr v-if="!comp.length && !sectionError.comp"><td colspan="3" class="c muted">未设置补偿</td></tr>
                </tbody>
              </table>
              <div class="row" style="margin-top: 10px">
                <select v-model="newCh" class="select" style="width: 90px" aria-label="通道">
                  <option v-for="channel in TEMP_CHANNELS" :key="channel" :value="channel">{{ channel }}</option>
                </select>
                <input v-model.number="newVal" class="input num" type="number" step="0.01" placeholder="℃" style="width: 100px" aria-label="补偿值" @keydown.enter="addComp" />
                <button class="btn btn-sm" :disabled="newVal === null" @click="addComp"><Plus :size="14" />添加</button>
                <span class="grow" />
                <button class="btn btn-primary" :disabled="dis || !compDirty" @click="writeComp">写入机台</button>
              </div>
            </Panel>
          </div>
        </template>

        <Panel v-else-if="tab === 'alarm'" flush>
          <div class="table-wrap" style="border-top: 0">
            <table class="table">
              <thead><tr><th>时间</th><th>级别</th><th>来源</th><th>代码</th><th>槽位</th><th>描述</th><th>状态</th></tr></thead>
              <tbody>
                <tr v-for="alarm in alarms" :key="alarm.id">
                  <td class="num fs-sm">{{ dt(alarm.time) }}</td>
                  <td><span class="tag" :class="LV[alarm.level][0]">{{ LV[alarm.level][1] }}</span></td>
                  <td class="fs-sm">{{ alarm.source }}</td>
                  <td class="mono fs-sm">{{ alarm.code }}</td>
                  <td class="mono">{{ alarm.slot_index ? `#${alarm.slot_index}` : '—' }}</td>
                  <td class="fs-sm" style="white-space: normal">{{ alarm.message }}</td>
                  <td><span class="tag" :class="alarm.acked ? '' : 'warn'">{{ alarm.acked ? '已确认' : '未确认' }}</span></td>
                </tr>
                <tr v-if="!alarms.length"><td colspan="7" class="c muted" style="height: 80px">这台机台没有异常记录</td></tr>
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel v-else flush>
          <div class="table-wrap" style="border-top: 0">
            <table class="table">
              <thead><tr><th>方案</th><th>plan_id</th><th>版本</th><th>装载</th><th>卸下</th><th class="r">测试片数</th></tr></thead>
              <tbody>
                <tr v-for="item in plans" :key="`${item.plan_id}-${item.from}`">
                  <td><b>{{ item.name }}</b> <span v-if="!item.to" class="tag primary">当前</span></td>
                  <td class="mono fs-sm">{{ item.plan_id }}</td>
                  <td class="num">v{{ item.version }}</td>
                  <td class="num fs-sm">{{ dt(item.from) }}</td>
                  <td class="num fs-sm">{{ item.to ? dt(item.to) : '—' }}</td>
                  <td class="r num">{{ item.runs.toLocaleString() }}</td>
                </tr>
                <tr v-if="!plans.length"><td colspan="6" class="c muted" style="height: 80px">还没有下发过方案</td></tr>
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fail { color: var(--c-danger); font-size: var(--fs-sm); margin: 8px 0; }
.lay { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 12px; align-items: start; }
.side { position: sticky; top: 0; }
.pad { padding: 10px; border-bottom: var(--bw) solid var(--c-border); }
.mlist { list-style: none; margin: 0; padding: 0; }
.mlist button { width: 100%; display: flex; align-items: center; gap: 6px; padding: 8px 12px; border: 0; border-bottom: var(--bw) solid var(--c-border); background: transparent; cursor: pointer; text-align: left; }
.mlist button:hover { background: var(--c-surface-2); }
.mlist button.on { background: var(--c-primary-weak); box-shadow: inset 3px 0 0 var(--c-primary); }
.head { display: flex; align-items: center; gap: 12px; padding: 14px 16px; background: var(--c-surface); border: var(--bw) solid var(--c-border); box-shadow: inset 0 3px 0 var(--c-accent); }
.head.dis { background: repeating-linear-gradient(-45deg, var(--c-surface) 0 10px, var(--c-surface-2) 10px 20px); box-shadow: inset 0 3px 0 var(--c-danger); }
.head h2 { font-size: var(--fs-xl); }
.notice { display: flex; gap: 10px; padding: 10px 14px; background: var(--c-danger-weak); border-left: 3px solid var(--c-danger); color: var(--c-danger); }
.notice p { color: var(--c-text-2); }
.tabs { display: flex; border-bottom: var(--bw) solid var(--c-border-strong); }
.tabs button { display: inline-flex; align-items: center; gap: 6px; height: 38px; padding: 0 14px; border: 0; background: transparent; color: var(--c-text-2); cursor: pointer; border-bottom: 3px solid transparent; margin-bottom: -1px; }
.tabs button:hover { color: var(--c-text); }
.tabs button[aria-selected='true'] { color: var(--c-text); font-weight: 700; border-bottom-color: var(--c-primary); }
.kv { display: flex; flex-direction: column; gap: 2px; padding: 10px 14px; background: var(--c-surface); border: var(--bw) solid var(--c-border); font-size: var(--fs-xs); color: var(--c-text-3); min-width: 0; }
.kv b { color: var(--c-text); font-size: var(--fs-md); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sug { display: flex; align-items: center; gap: 8px; padding: 8px 10px; margin-bottom: 10px; background: var(--c-primary-weak); border-left: 3px solid var(--c-primary); }
.sug svg { color: var(--c-primary); }
.cell { height: 28px; width: 110px; text-align: right; }
</style>
