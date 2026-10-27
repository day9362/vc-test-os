<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import {
  Bot, CheckCircle2, ClipboardList, Cloud, Database, Eye, EyeOff, FlaskConical, Gauge, Loader2, PlugZap, RefreshCw, RotateCcw, Save, Scale, Server, XCircle, Zap,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Panel from '@/components/Panel.vue'
import { api } from '@/api/http'
import type { FaultInfo } from '@/api/types'
import { useSettingsStore } from '@/stores/settings'
import { useAppStore } from '@/stores/app'
import { AI_MODULES, faultCatalog, SCENARIOS } from '@/mock/cluster'
import { ago, dt } from '@/utils/format'

const s = useSettingsStore()
const app = useAppStore()
const d = computed(() => s.draft)

const SECTIONS = [
  { id: 'source', label: '数据源', icon: Server },
  { id: 'jobs', label: '同步频率', icon: RefreshCw },
  { id: 'sim', label: '仿真平台', icon: FlaskConical },
  { id: 'storage', label: '本地存储', icon: Database },
  { id: 'ai', label: 'AI 接入', icon: Bot },
  { id: 'rules', label: '判定与告警', icon: Scale },
  { id: 'audit', label: '审计日志', icon: ClipboardList },
]
const go = (id: string) => document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

const testing = ref(false)
const testResult = ref<null | { ok: boolean; ms: number; text: string }>(null)
async function testConn() {
  testing.value = true
  testResult.value = null
  const url = d.value.source === 'sim' ? d.value.sim.base_url : d.value.cluster.base_url
  try {
    const result = await api<{ ok: boolean; latency_ms: number; machines: number; reachable: number; server_version: string }>('/settings/test-connection', {
      method: 'POST',
      body: JSON.stringify({ source: d.value.source, base_url: url, token: d.value.cluster.token }),
    })
    testResult.value = {
      ok: result.ok,
      ms: result.latency_ms,
      text: result.ok
        ? `${result.machines} 台机台 · ${result.reachable} 台可通信${result.server_version ? ` · ${result.server_version}` : ''}`
        : '连不上这个地址',
    }
  } catch (err) {
    testResult.value = { ok: false, ms: 0, text: err instanceof Error ? err.message : '连不上这个地址' }
  }
  testing.value = false
}

const showKey = ref(false)
const showToken = ref(false)
const minInterval = (k: string) => (k === 'slots' || k === 'samples' ? 1 : k === 'fleet' ? 1 : 5)
const reqPerMin = computed(() => d.value.jobs.filter((j) => j.enabled).reduce((a, j) => a + (60 / j.interval_s) * (/\{id\}/.test(j.api) ? 12 : 1), 0))

const SPEEDS = [1, 2, 5, 10, 30]
const machines = ref<string[]>([])
const scenarioTarget = ref('M01')
const scenarios = ref(SCENARIOS.map((item) => ({ name: item.name, text: item.text })))
const faults = ref(faultCatalog.map((item) => ({ kind: item.kind, layer: item.layer })))
const scenario = ref(scenarios.value[0].name)
const fault = ref(faults.value[0].kind)
const jobRuns = ref<Record<string, { last_at: number | null; elapsed_ms: number | null; failed: boolean | null }>>({})
const auditRows = ref<{ audit_id: string; time: number; actor: string; action: string; machine_id: string }[]>([])
const auditHint = ref('打开本页会读取最近的写操作')

async function loadAudit() {
  try {
    const body = await api<{ items: { audit_id: string; time: number; actor: string; action: string; machine_id: string }[] }>('/audit?limit=30')
    auditRows.value = body.items || []
    auditHint.value = `${auditRows.value.length} 条写操作`
  } catch (err) {
    auditRows.value = []
    auditHint.value = err instanceof Error ? err.message : '审计日志没有读到'
  }
}

function jobText(key: string) {
  const row = jobRuns.value[key]
  if (!row || row.last_at == null) return '还没有跑过'
  const state = row.failed ? '失败' : '成功'
  return `${state} · ${ago(row.last_at)} · ${row.elapsed_ms ?? 0} ms`
}

async function setSpeed(speed: number) {
  d.value.sim.speed = speed
  if (s.saved.source !== 'sim') return
  try {
    await api('/sim/clock', {
      method: 'PUT',
      body: JSON.stringify({ speed }),
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
    s.commitSpeed(speed)
  } catch (err) {
    d.value.sim.speed = s.saved.sim.speed
    app.toast({ kind: 'danger', title: '仿真倍率没有改成', desc: err instanceof Error ? err.message : '' })
  }
}

async function inject(kind: 'scenario' | 'fault') {
  const what = kind === 'scenario' ? scenario.value : fault.value
  const ok = await app.confirm({
    title: `向 ${scenarioTarget.value} 注入 ${what}`,
    desc: kind === 'scenario' ? `给 ${scenarioTarget.value} 套上场景 ${what}` : `给 ${scenarioTarget.value} 注入故障 ${what}`,
    danger: true, confirmText: '注入',
  })
  if (!ok) return
  try {
    if (kind === 'scenario') {
      await api(`/sim/scenarios/${scenario.value}/apply`, {
        method: 'POST',
        body: JSON.stringify({ machine_id: scenarioTarget.value }),
        headers: { 'Idempotency-Key': crypto.randomUUID() },
      })
    } else {
      await api('/sim/faults', {
        method: 'POST',
        body: JSON.stringify({ machine_id: scenarioTarget.value, kind: fault.value }),
        headers: { 'Idempotency-Key': crypto.randomUUID() },
      })
    }
    app.toast({ kind: 'warn', title: `已注入 ${what}`, desc: `${scenarioTarget.value} · 可在设备配置页查看效果` })
  } catch (err) {
    app.toast({ kind: 'danger', title: '没有注入', desc: err instanceof Error ? err.message : '' })
  }
}

async function save() {
  try {
    await s.save()
    app.toast({ kind: 'ok', title: '设置已保存', desc: '后端会在下一个轮询周期应用新频率' })
  } catch (err) {
    app.toast({ kind: 'danger', title: '设置没有保存', desc: err instanceof Error ? err.message : '' })
  }
}

onMounted(async () => {
  try {
    await s.load()
  } catch (err) {
    app.toast({ kind: 'danger', title: '设置没有读到', desc: err instanceof Error ? err.message : '' })
  }
  const [status, fleet] = await Promise.all([
    api<{ items: { key: string; last_at: number | null; elapsed_ms: number | null; failed: boolean | null }[] }>('/sync/jobs/status').catch(() => ({ items: [] })),
    api<{ machine_id: string }[]>('/machines').catch(() => []),
  ])
  jobRuns.value = Object.fromEntries(status.items.map((item) => [item.key, item]))
  machines.value = fleet.map((item) => item.machine_id)
  if (machines.value.length && !machines.value.includes(scenarioTarget.value)) scenarioTarget.value = machines.value[0]
  await loadAudit()
  if (s.saved.source !== 'sim') return
  const [scene, catalog] = await Promise.all([
    api<{ items: { name: string }[] }>('/sim/scenarios').catch(() => null),
    api<{ items: Pick<FaultInfo, 'kind' | 'layer'>[] }>('/sim/fault-catalog').catch(() => null),
  ])
  if (scene?.items.length) {
    scenarios.value = scene.items.map((item) => ({ name: item.name, text: SCENARIOS.find((row) => row.name === item.name)?.text || item.name }))
    if (!scenarios.value.some((item) => item.name === scenario.value)) scenario.value = scenarios.value[0].name
  }
  if (catalog?.items.length) {
    faults.value = catalog.items.filter((item) => item.kind)
    if (!faults.value.some((item) => item.kind === fault.value)) fault.value = faults.value[0].kind
  }
})
async function reset() {
  if (await app.confirm({ title: '恢复默认设置', desc: '所有项恢复为默认值，保存后才生效。', confirmText: '恢复默认' })) s.reset()
}
onBeforeRouteLeave(async () => {
  if (!s.dirty) return true
  const ok = await app.confirm({ title: '有未保存的修改', desc: '离开后这些修改会丢失。', danger: true, confirmText: '放弃修改并离开' })
  if (ok) s.discard()
  return ok
})
</script>

<template>
  <div class="page">
    <PageHeader title="系统设置" desc="集群地址、同步频率与平台自身配置 · 由本地后端读取并生效">
      <button class="btn" @click="reset"><RotateCcw :size="16" />恢复默认</button>
    </PageHeader>

    <div class="lay">
      <nav class="toc" aria-label="设置分区">
        <button v-for="x in SECTIONS" :key="x.id" @click="go(x.id)"><component :is="x.icon" :size="15" />{{ x.label }}</button>
      </nav>

      <div class="col" style="gap: 12px; min-width: 0">
        <!-- 数据源 -->
        <Panel id="sec-source" title="数据源" code="SOURCE" :icon="Server">
          <div class="src">
            <button :class="{ on: d.source === 'cluster' }" :aria-pressed="d.source === 'cluster'" @click="d.source = 'cluster'">
              <Cloud :size="20" /><b>真实集群</b><span class="fs-xs muted">产线 12 台 X9601，经边缘网关访问</span>
            </button>
            <button :class="{ on: d.source === 'sim' }" :aria-pressed="d.source === 'sim'" @click="d.source = 'sim'">
              <FlaskConical :size="20" /><b>仿真平台</b><span class="fs-xs muted">cluster.simuoss.cn · 接口与真实集群一致</span>
            </button>
          </div>
          <div class="fgrid" style="margin-top: 14px">
            <div class="field span-2">
              <label for="base">接口地址</label>
              <div class="row">
                <input v-if="d.source === 'cluster'" id="base" v-model="d.cluster.base_url" class="input mono grow" />
                <input v-else id="base" v-model="d.sim.base_url" class="input mono grow" />
                <button class="btn" :disabled="testing" @click="testConn"><Loader2 v-if="testing" :size="16" class="spin" /><PlugZap v-else :size="16" />测试连接</button>
              </div>
              <span v-if="testResult" class="hint row gap-4" :class="testResult.ok ? 't-ok' : 't-danger'">
                <CheckCircle2 v-if="testResult.ok" :size="13" /><XCircle v-else :size="13" />
                {{ testResult.ok ? `连接正常 · ${testResult.ms} ms · ` : '' }}{{ testResult.text }}
              </span>
              <span v-else class="hint">后端用此地址请求 /api/fleet、/api/machines/{id} 等接口</span>
            </div>
            <div v-if="d.source === 'cluster'" class="field">
              <label for="tk">访问令牌</label>
              <div class="row">
                <input id="tk" v-model="d.cluster.token" class="input mono grow" :type="showToken ? 'text' : 'password'" placeholder="未设置" autocomplete="off" />
                <button class="btn btn-icon" v-tip="showToken ? '隐藏' : '显示'" @click="showToken = !showToken"><EyeOff v-if="showToken" :size="16" /><Eye v-else :size="16" /></button>
              </div>
            </div>
            <div class="field">
              <label for="to">请求超时</label>
              <div class="unit-in"><input id="to" v-model.number="d.cluster.timeout_s" class="input num" type="number" min="1" max="60" /><span>s</span></div>
            </div>
            <div class="field">
              <label for="rt">失败重试</label>
              <div class="unit-in"><input id="rt" v-model.number="d.cluster.retries" class="input num" type="number" min="0" max="5" /><span>次</span></div>
            </div>
            <div class="field">
              <label>机台返回 503（通信断开）时</label>
              <div class="seg">
                <button :aria-pressed="d.cluster.on_503 === 'skip'" @click="d.cluster.on_503 = 'skip'">跳过该机台</button>
                <button :aria-pressed="d.cluster.on_503 === 'pause'" @click="d.cluster.on_503 = 'pause'">暂停全部同步</button>
              </div>
            </div>
          </div>
        </Panel>

        <!-- 同步频率 -->
        <Panel id="sec-jobs" title="同步频率" code="SYNC JOBS" :icon="RefreshCw" flush>
          <template #actions><span class="fs-xs muted num">约 {{ Math.round(reqPerMin).toLocaleString() }} 次请求 / 分钟</span></template>
          <div class="table-wrap" style="border-top: 0">
            <table class="table">
              <thead><tr><th style="width: 60px">启用</th><th>任务</th><th>接口</th><th style="width: 150px">间隔</th><th>最近</th><th>说明</th></tr></thead>
              <tbody>
                <tr v-for="j in d.jobs" :key="j.key" :class="{ off: !j.enabled }">
                  <td><label class="sw"><input v-model="j.enabled" type="checkbox" :aria-label="`启用 ${j.name}`" /><i /></label></td>
                  <td class="fw-6">{{ j.name }}</td>
                  <td class="mono fs-xs">{{ j.api }}</td>
                  <td>
                    <div class="unit-in sm">
                      <input v-model.number="j.interval_s" class="input num" type="number" :min="minInterval(j.key)" :disabled="!j.enabled" :aria-label="`${j.name} 间隔`" />
                      <span>s</span>
                    </div>
                  </td>
                  <td class="fs-xs text-2">{{ jobText(j.key) }}</td>
                  <td class="fs-sm text-2" style="white-space: normal">{{ j.note }}<span v-if="j.interval_s < minInterval(j.key)" class="t-danger"> · 最小 {{ minInterval(j.key) }} s</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <template #footer>后端按这些频率轮询集群并写入本地库，前端通过 WebSocket 接收推送，不直接请求集群</template>
        </Panel>

        <!-- 仿真 -->
        <Panel id="sec-sim" title="仿真平台" code="SIM ONLY" :icon="FlaskConical" :class="{ dim: d.source !== 'sim' }">
          <template #actions><span v-if="d.source !== 'sim'" class="tag">当前数据源不是仿真平台</span></template>
          <div class="fgrid">
            <div class="field">
              <label>仿真倍率 <span class="mono fs-xs muted">PUT /api/fleet/clock</span></label>
              <div class="seg">
                <button v-for="v in SPEEDS" :key="v" :aria-pressed="d.sim.speed === v" @click="setSpeed(v)">×{{ v }}</button>
              </div>
              <span class="hint">180 s 的方案在 ×10 下约 18 s 完成</span>
            </div>
            <div class="field span-2">
              <label>Ground truth</label>
              <label class="opt">
                <input v-model="d.sim.use_ground_truth" type="checkbox" />
                <span>拉取 /api/runs/{id}/ground-truth，用于评估异常归因算法的准确率<span class="tag warn" style="margin-left: 6px">仅用于算法评估</span></span>
              </label>
              <span class="hint">真实集群没有这个接口；打开后不会影响判定与报告</span>
            </div>
          </div>
          <div class="inject">
            <span class="code-label">故障注入</span>
            <select v-model="scenarioTarget" class="select" style="width: 90px" aria-label="目标机台">
              <option v-for="id in (machines.length ? machines : ['M01'])" :key="id" :value="id">{{ id }}</option>
            </select>
            <select v-model="scenario" class="select" aria-label="场景">
              <option v-for="x in scenarios" :key="x.name" :value="x.name">{{ x.name }} · {{ x.text }}</option>
            </select>
            <button class="btn" :disabled="d.source !== 'sim'" @click="inject('scenario')"><Zap :size="16" />应用场景</button>
            <span class="vdivider" />
            <select v-model="fault" class="select" aria-label="故障">
              <option v-for="f in faults" :key="f.kind" :value="f.kind">{{ f.kind }} · {{ f.layer }}</option>
            </select>
            <button class="btn" :disabled="d.source !== 'sim'" @click="inject('fault')"><Zap :size="16" />注入故障</button>
          </div>
        </Panel>

        <!-- 存储 -->
        <Panel id="sec-storage" title="本地存储" code="POSTGRES + TIMESCALE" :icon="Database">
          <div class="fgrid">
            <div class="field span-2"><label for="dsn">数据库连接</label><input id="dsn" v-model="d.storage.dsn" class="input mono" /></div>
            <div class="field"><label for="os">对象存储（报告、图表）</label><input id="os" v-model="d.storage.object_store" class="input mono" /></div>
            <div class="field"><label for="sd">过程曲线保留</label><div class="unit-in"><input id="sd" v-model.number="d.storage.samples_days" class="input num" type="number" /><span>天</span></div><span class="hint">samples 时序表，超期自动压缩后删除</span></div>
            <div class="field"><label for="rd">测试记录保留</label><div class="unit-in"><input id="rd" v-model.number="d.storage.runs_days" class="input num" type="number" /><span>天</span></div></div>
            <div class="field"><label>5 分钟连续聚合</label><label class="opt"><input v-model="d.storage.agg_5m" type="checkbox" /><span>启用 agg_5m（运行总览依赖此表）</span></label></div>
          </div>
        </Panel>

        <!-- AI -->
        <Panel id="sec-ai" title="AI 接入" code="LLM GATEWAY" :icon="Bot">
          <div class="fgrid">
            <div class="field span-2"><label for="ai">接口地址（OpenAI 兼容）</label><input id="ai" v-model="d.ai.base_url" class="input mono" /></div>
            <div class="field">
              <label for="key">API Key</label>
              <div class="row">
                <input id="key" v-model="d.ai.api_key" class="input mono grow" :type="showKey ? 'text' : 'password'" placeholder="sk-…" autocomplete="off" />
                <button class="btn btn-icon" v-tip="showKey ? '隐藏' : '显示'" @click="showKey = !showKey"><EyeOff v-if="showKey" :size="16" /><Eye v-else :size="16" /></button>
              </div>
            </div>
            <div class="field"><label for="bg">月度预算</label><div class="unit-in"><input id="bg" v-model.number="d.ai.monthly_budget_m" class="input num" type="number" /><span>M tokens</span></div></div>
            <div class="field"><label for="al">用到预算的</label><div class="unit-in"><input id="al" v-model.number="d.ai.alert_pct" class="input num" type="number" min="10" max="100" /><span>% 提醒</span></div></div>
          </div>
          <h4 class="code-label" style="margin: 16px 0 8px">各模块使用的模型</h4>
          <div class="mods">
            <div v-for="m in AI_MODULES" :key="m.id" class="mod">
              <div class="grow" style="min-width: 0"><b class="fs-sm">{{ m.name }}</b><div class="fs-xs muted ellipsis">{{ m.where }} · {{ m.trigger }}</div></div>
              <select v-model="d.ai.models[m.id]" class="select" style="width: 140px" :aria-label="`${m.name} 模型`">
                <option value="deepseek-v3">deepseek-v3</option>
                <option value="qwen3-max">qwen3-max</option>
                <option value="qwen3-32b-local">qwen3-32b（本地）</option>
              </select>
            </div>
          </div>
        </Panel>

        <!-- 规则 -->
        <Panel id="sec-rules" title="判定与告警" code="RULES" :icon="Gauge">
          <div class="fgrid">
            <div class="field"><label for="dc">设备异常阈值（通道漂移）</label><div class="unit-in"><input id="dc" v-model.number="d.rules.drift_c" class="input num" type="number" step="0.01" /><span>℃</span></div><span class="hint">超过即记为 EQUIPMENT_ANOMALY</span></div>
            <div class="field"><label for="ack">告警确认超时</label><div class="unit-in"><input id="ack" v-model.number="d.rules.ack_timeout_min" class="input num" type="number" /><span>分钟</span></div><span class="hint">超时未确认会升级通知</span></div>
            <div class="field">
              <label>趋势规则（Western Electric）</label>
              <div class="seg">
                <button v-for="r in ['WE-1', 'WE-2', 'WE-3', 'WE-4']" :key="r" :aria-pressed="d.rules.we_rules.includes(r)" @click="d.rules.we_rules = d.rules.we_rules.includes(r) ? d.rules.we_rules.filter((x) => x !== r) : [...d.rules.we_rules, r]">{{ r }}</button>
              </div>
            </div>
            <label class="opt span-2"><input v-model="d.rules.sentinel_as_data_anomaly" type="checkbox" /><span>哨兵值（99999 / 9999 接触不良、-1 板卡无响应、-2 无法解析）记为数据异常，不计入产品缺陷</span></label>
            <label class="opt"><input v-model="d.rules.degraded_alarm" type="checkbox" /><span>通信降级（DEGRADED）时告警</span></label>
          </div>
        </Panel>

        <Panel id="sec-audit" title="审计日志" code="AUDIT" :icon="ClipboardList">
          <template #actions>
            <button class="btn btn-ghost btn-sm" @click="loadAudit"><RefreshCw :size="14" />刷新</button>
          </template>
          <p class="fs-sm muted" style="margin: 0 0 8px">{{ auditHint }}</p>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>机台</th><th>audit_id</th></tr></thead>
              <tbody>
                <tr v-for="row in auditRows" :key="row.audit_id">
                  <td class="num fs-sm">{{ dt(row.time) }}</td>
                  <td class="mono fs-xs">{{ row.actor }}</td>
                  <td class="mono fs-xs">{{ row.action }}</td>
                  <td class="mono">{{ row.machine_id || '—' }}</td>
                  <td class="mono fs-xs">{{ row.audit_id }}</td>
                </tr>
                <tr v-if="!auditRows.length"><td colspan="5" class="c muted" style="height: 64px">还没有写操作审计</td></tr>
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>

    <Transition name="bar">
      <div v-if="s.dirty" class="savebar">
        <span class="hazard hz" />
        <b>有未保存的修改</b>
        <span class="grow" />
        <button class="btn" @click="s.discard()">放弃</button>
        <button class="btn btn-primary" @click="save"><Save :size="16" />保存</button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.lay { display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 12px; align-items: start; padding-bottom: 48px; }
.toc { position: sticky; top: 0; display: flex; flex-direction: column; border: var(--bw) solid var(--c-border); background: var(--c-surface); }
.toc button { display: flex; align-items: center; gap: 8px; height: 38px; padding: 0 12px; border: 0; border-bottom: var(--bw) solid var(--c-border); background: transparent; cursor: pointer; text-align: left; color: var(--c-text-2); }
.toc button:last-child { border-bottom: 0; }
.toc button:hover { background: var(--c-surface-2); color: var(--c-text); box-shadow: inset 3px 0 0 var(--c-primary); }
.panel { scroll-margin-top: 12px; }
.src { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.src button { display: grid; grid-template-columns: auto 1fr; grid-template-rows: auto auto; column-gap: 10px; align-items: center; padding: 12px 14px; text-align: left; border: var(--bw) solid var(--c-border-strong); background: var(--c-surface); cursor: pointer; }
.src button svg { grid-row: span 2; color: var(--c-text-3); }
.src button:hover { border-color: var(--c-text-2); }
.src button.on { border-color: var(--c-primary); background: var(--c-primary-weak); box-shadow: inset 0 0 0 1px var(--c-primary); }
.src button.on svg { color: var(--c-primary); }
.fgrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; align-items: start; }
.unit-in { display: flex; }
.unit-in .input { flex: 1; min-width: 0; border-right: 0; }
.unit-in span { display: grid; place-items: center; padding: 0 10px; border: var(--bw) solid var(--c-border-strong); background: var(--c-surface-2); color: var(--c-text-3); font-size: var(--fs-sm); white-space: nowrap; }
.unit-in.sm .input { height: 28px; }
.opt { display: flex; gap: 8px; align-items: flex-start; cursor: pointer; font-size: var(--fs-sm); }
.opt input { margin-top: 4px; accent-color: var(--c-primary); }
.sw { position: relative; display: inline-block; width: 34px; height: 18px; cursor: pointer; }
.sw input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; }
.sw i { position: absolute; inset: 0; background: var(--c-surface-3); border: var(--bw) solid var(--c-border-strong); transition: background-color var(--dur) var(--ease); }
.sw i::after { content: ''; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px; background: var(--c-text-3); transition: transform var(--dur) var(--ease); }
.sw input:checked + i { background: var(--c-primary); border-color: var(--c-primary); }
.sw input:checked + i::after { transform: translateX(16px); background: #fff; }
.sw input:focus-visible + i { outline: 2px solid var(--c-focus); outline-offset: 1px; }
tr.off td { color: var(--c-text-3); }
.dim { opacity: 0.6; }
.inject { display: flex; align-items: center; gap: 8px; margin-top: 16px; padding-top: 14px; border-top: var(--bw) dashed var(--c-border); flex-wrap: wrap; }
.mods { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.mod { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: var(--bw) solid var(--c-border); background: var(--c-surface-2); }
.spin { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.savebar { position: sticky; bottom: 0; margin: 0 -20px -32px; display: flex; align-items: center; gap: 10px; padding: 10px 20px 10px 28px; background: var(--c-surface); border-top: 2px solid var(--c-warn); box-shadow: 0 -8px 20px -12px rgba(0, 0, 0, 0.25); z-index: 5; }
.hz { position: absolute; left: 0; top: 0; bottom: 0; width: 8px; }
.bar-enter-active, .bar-leave-active { transition: transform 160ms var(--ease), opacity 160ms var(--ease); }
.bar-enter-from, .bar-leave-to { transform: translateY(100%); opacity: 0; }
</style>
