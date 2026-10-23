<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowUp, BarChart3, Bot, Check, ChevronRight, Database, FileCode2, Loader2, Plus, ShieldCheck, Sparkles, SquareTerminal, User, Wrench, X,
} from 'lucide-vue-next'
import Panel from '@/components/Panel.vue'
import EChart from '@/components/EChart.vue'
import { useLiveStore } from '@/stores/live'
import { useAppStore } from '@/stores/app'
import { useTokens } from '@/composables/useTokens'
import { models, plans } from '@/mock/cluster'
import { hms } from '@/utils/format'

const live = useLiveStore()
const app = useAppStore()
const route = useRoute()
const router = useRouter()
const tk = useTokens()

type Block =
  | { type: 'tool'; name: string; args: string; result: string; write?: false }
  | { type: 'chart'; title: string; option: () => any }
  | { type: 'plan'; plan_id: string; name: string; fields: [string, string][] }
  | { type: 'action'; method: 'POST' | 'PUT'; path: string; body: Record<string, any> | null; desc: string; risk: 'low' | 'high'; status: 'pending' | 'done' | 'rejected' }
interface Msg { id: number; role: 'user' | 'agent'; text: string; blocks: Block[]; module?: string; tokens?: [number, number]; time: number }

const CAPS = [
  { key: 'analysis', icon: BarChart3, title: '跨批次分析', module: 'agent.analysis', prompts: ['对比最近 3 个 tb172 批次的良率，找出差异原因', 'M07 的 Rc 为什么一直偏高？', '本班 Temp_T1-T14 不合格是机台问题还是来料问题？'] },
  { key: 'plan', icon: FileCode2, title: '自然语言 → 测试方案', module: 'agent.plan', prompts: ['给 HVP1307G17-1 做一个 3.5W、120g、测 3 分钟的方案', 'tb179 竖放 90 度测 4 分钟，温差上限 4.2'] },
  { key: 'ops', icon: Wrench, title: '设备操作', module: 'agent.ops', prompts: ['把 M07 的 T1 通道补偿 -0.18 ℃', '复位 M05 并重新上电', '停止当前连续生产', '让 M08 结束维修'] },
]

let mid = 0
const msgs = ref<Msg[]>([])
const input = ref('')
const busy = ref(false)
const scroller = ref<HTMLElement>()
const scope = ref({ model: 'tb172', batches: live.batchStats.filter((b) => b.model === 'tb172').slice(0, 3).map((b) => b.batch_id), machines: [] as string[] })

const scroll = () => nextTick(() => scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' }))
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function analysis(q: string): Omit<Msg, 'id' | 'role' | 'time'> {
  const bs = live.batchStats.filter((b) => scope.value.batches.includes(b.batch_id))
  const L = bs.length ? bs : live.batchStats.slice(0, 3)
  const ms = ['M01', 'M02', 'M03', 'M04', 'M06', 'M07', 'M11']
  const yields = (i: number) => ms.map((m) => +(98.4 - (m === 'M07' ? 2.6 + i * 0.4 : 0) - (m === 'M03' ? 0.6 : 0) + Math.sin(i * 3 + m.charCodeAt(2)) * 0.4).toFixed(2))
  return {
    module: 'agent.analysis', tokens: [9800, 1320],
    text: `${L.length} 个批次里，M07 的良率比其余机台低 2.6–3.4 个百分点，且越到后面的批次差距越大；同一批次在其它机台上表现正常，说明问题在机台而不是来料。\n\nM07 的 T1 通道在 10 片标准样品复测中估计漂移 +0.18 ℃（LINEAR，仍在增长），已超过 0.15 ℃ 的设备异常阈值。T1 偏高会让 Temp_T0-T1 偏小、Rc = (T1−Ta)/P 偏大，和 M07 Rc 偏高 +0.094 ℃/W 一致。\n\n建议：先给 M07 的 T1 写入 −0.18 ℃ 补偿，再用标准样品复测确认；补偿前 M07 上判不合格的 ${Math.round(L.length * 9)} 片建议复测，不要直接报废。`,
    blocks: [
      { type: 'tool', name: 'sql · 本地库', args: `SELECT batch_id, machine_id, avg(passed::int) FROM runs WHERE batch_id IN (${L.length} 个) GROUP BY 1, 2`, result: `${L.length * ms.length} 行` },
      { type: 'tool', name: 'GET /api/machines/M07/drifts', args: '', result: 'T1 · LINEAR · current +0.18 ℃；Ta · HOURLY · +0.05 ℃' },
      { type: 'chart', title: '各批次分机台良率', option: () => ({
        grid: { left: 40, right: 12, top: 28, bottom: 24 }, legend: {},
        xAxis: { type: 'category', data: ms }, yAxis: { type: 'value', min: 94, max: 100 },
        series: L.map((b, i) => ({ name: b.batch_id.slice(-8), type: 'bar', data: yields(i), itemStyle: { color: tk.value.chart[i % 6] } })),
      }) },
      { type: 'action', method: 'PUT', path: '/api/machines/M07/compensation', body: { mode: 'add', compensation: [{ channel: 'T1', value: -0.18 }] }, desc: 'M07 · T1 通道补偿 −0.18 ℃（叠加到现有补偿）', risk: 'high', status: 'pending' },
    ],
  }
}
function planIntent(q: string): Omit<Msg, 'id' | 'role' | 'time'> {
  const hvp = /HVP|3\.5/i.test(q)
  const power = hvp ? 3.5 : 2.5
  const force = +(q.match(/(\d+)\s*g/)?.[1] ?? (hvp ? 120 : 100))
  const dur = +(q.match(/(\d+)\s*分钟/)?.[1] ?? 3) * 60
  const t1x = +(q.match(/温差上限\s*([\d.]+)/)?.[1] ?? (hvp ? 4.8 : 4.0))
  const id = `DRAFT-${String(10 + mid).padStart(4, '0')}`
  return {
    module: 'agent.plan', tokens: [3900, 860],
    text: `已生成方案草稿，所有字段都在 X9601 能力范围内（功率 0.1–10 W、压紧力 20–300 g、时长 1–600 s）。${hvp ? 'HVP1307G17-1 参考功率 3.5 W，按惯例 power_w 判定 3.4–3.6 W。' : ''}草稿只保存在本地，需要在「测试方案」页确认后发布，再到「测试执行」下发。`,
    blocks: [
      { type: 'tool', name: 'GET /api/machines/M01', args: 'capability', result: 'duration 1–600 s · power 0.1–10 W · force 20–300 g · 19 温度 / 14 压力通道' },
      { type: 'plan', plan_id: id, name: q.slice(0, 20), fields: [
        ['power_w', `${power} W`], ['force_g', `${force} g`], ['duration_s', `${dur} s`], ['orientation', /90/.test(q) ? '90°' : '0°'],
        ['Temp_T0-T1', `≤ ${hvp ? 3.4 : 2.8} ℃`], ['Temp_T1-T2…T12', `≤ ${t1x} ℃`], ['Temp_T1-T13/14', '跳过'], ['power_w 判定', `${power - 0.1}–${power + 0.1} W`],
      ] },
    ],
  }
}
function opsIntent(q: string): Omit<Msg, 'id' | 'role' | 'time'> {
  const m = q.match(/M\d{2}/)?.[0] ?? 'M05'
  const mach = live.machine(m)
  const blocks: Block[] = [{ type: 'tool', name: `GET /api/machines/${m}`, args: '', result: mach ? `status ${mach.status} · comm ${mach.comm_status}${mach.alarm ? ' · ' + mach.alarm : ''}` : '未找到' }]
  let text = ''
  if (mach?.comm_status === 'DISCONNECTED') {
    text = `${m} 当前通信断开，所有指令都会返回 503，无法执行。请先在现场检查网线 / 交换机，恢复后我再继续。`
  } else if (/补偿/.test(q)) {
    const v = +(q.match(/(-?[\d.]+)\s*℃/)?.[1] ?? -0.18)
    text = `${m} T1 当前补偿 0，估计漂移 +0.18 ℃。写入后新测试立即生效，正在测量的片子不受影响。`
    blocks.push({ type: 'action', method: 'PUT', path: `/api/machines/${m}/compensation`, body: { mode: 'add', compensation: [{ channel: 'T1', value: v }] }, desc: `${m} · T1 补偿 ${v} ℃`, risk: 'high', status: 'pending' })
  } else if (/停止/.test(q)) {
    text = `当前连续生产批次 ${live.production?.batch_id ?? '—'}，剩余 ${live.production?.queue_remaining ?? 0} 片。停止在取下一片前生效，正在测的片子会测完。`
    blocks.push({ type: 'action', method: 'POST', path: '/api/fleet/production/stop', body: null, desc: '停止连续生产', risk: 'high', status: 'pending' })
  } else if (/维修/.test(q)) {
    text = `${m} 处于 MAINTENANCE。结束维修后机台回到 OFFLINE，需要再上电才会参与生产。`
    blocks.push({ type: 'action', method: 'POST', path: `/api/machines/${m}/maintenance`, body: { on: false }, desc: `${m} · 结束维修`, risk: 'low', status: 'pending' })
  } else {
    text = `${m} 处于 ${mach?.status}（${mach?.alarm || '无报警'}）。按顺序执行：先 reset 清除故障，再 power-on。两步都需要你确认。`
    blocks.push({ type: 'action', method: 'POST', path: `/api/machines/${m}/reset`, body: null, desc: `${m} · 复位（清除 FAULT，槽位 ERROR → IDLE）`, risk: 'low', status: 'pending' })
    blocks.push({ type: 'action', method: 'POST', path: `/api/machines/${m}/power-on`, body: null, desc: `${m} · 上电`, risk: 'low', status: 'pending' })
  }
  return { module: 'agent.ops', tokens: [2600, 410], text, blocks }
}

async function send(q = input.value) {
  q = q.trim()
  if (!q || busy.value) return
  input.value = ''
  msgs.value.push({ id: ++mid, role: 'user', text: q, blocks: [], time: Date.now() })
  busy.value = true
  scroll()
  await sleep(900)
  const r = /方案|测\s*\d+\s*分钟|竖放/.test(q) ? planIntent(q) : /补偿|复位|上电|关机|停止|维修|下发/.test(q) ? opsIntent(q) : analysis(q)
  msgs.value.push({ id: ++mid, role: 'agent', time: Date.now(), ...r })
  busy.value = false
  scroll()
}

async function approve(b: Extract<Block, { type: 'action' }>) {
  const ok = await app.confirm({
    title: '执行集群操作',
    desc: `${b.method} ${b.path}${b.body ? '\n' + JSON.stringify(b.body) : ''}`,
    confirmText: '确认执行',
    danger: b.risk === 'high',
    typeToConfirm: b.risk === 'high' ? 'CONFIRM' : undefined,
    checklist: b.risk === 'high' ? ['已核对目标机台与参数', '知悉此操作会写入集群并记录到操作日志'] : undefined,
  })
  if (!ok) return
  b.status = 'done'
  app.toast({ kind: 'ok', title: '已执行', desc: `${b.method} ${b.path} · 200` })
}
function reject(b: Extract<Block, { type: 'action' }>) {
  b.status = 'rejected'
  app.toast({ kind: 'info', title: '已拒绝该操作', action: { label: '撤销', run: () => (b.status = 'pending') } })
}

const pending = computed(() => msgs.value.flatMap((m) => m.blocks.filter((b): b is Extract<Block, { type: 'action' }> => b.type === 'action' && b.status === 'pending')))
const sessionTokens = computed(() => msgs.value.reduce((a, m) => a + (m.tokens ? m.tokens[0] + m.tokens[1] : 0), 0))
const MODULE_TEXT: Record<string, string> = { 'agent.analysis': '跨批次分析', 'agent.plan': '方案生成', 'agent.ops': '设备操作' }

function toggleBatch(id: string) {
  const s = scope.value.batches
  scope.value.batches = s.includes(id) ? s.filter((x) => x !== id) : [...s, id]
}
function newSession() {
  msgs.value = []
}

onMounted(() => {
  if (route.query.q) { send(String(route.query.q)); router.replace({ query: {} }) }
  else send(CAPS[0].prompts[0])
})
</script>

<template>
  <div class="agent">
    <!-- 左：能力 -->
    <aside class="left">
      <button class="btn btn-primary" style="width: 100%" @click="newSession"><Plus :size="16" />新对话</button>
      <div v-for="c in CAPS" :key="c.key" class="cap">
        <h4><component :is="c.icon" :size="14" />{{ c.title }}<span class="code-label">{{ c.module }}</span></h4>
        <button v-for="p in c.prompts" :key="p" class="pr" :disabled="busy" @click="send(p)">
          <span>{{ p }}</span><ChevronRight :size="14" />
        </button>
      </div>
      <div class="safe">
        <ShieldCheck :size="16" />
        <p>Agent 只能读取本地库与集群的只读接口。写操作（补偿、上电、下发、停止…）一律生成待确认卡片，由你批准后才调用集群 API。</p>
      </div>
    </aside>

    <!-- 中：对话 -->
    <section class="center">
      <div ref="scroller" class="msgs">
        <div v-for="m in msgs" :key="m.id" class="msg" :class="m.role">
          <div class="av"><User v-if="m.role === 'user'" :size="16" /><Bot v-else :size="16" /></div>
          <div class="bd">
            <div class="meta">
              <b>{{ m.role === 'user' ? '你' : 'Agent' }}</b>
              <span v-if="m.module" class="tag primary">{{ MODULE_TEXT[m.module] }}</span>
              <span class="num">{{ hms(m.time) }}</span>
              <span v-if="m.tokens" class="num grow" style="text-align: right">{{ m.tokens[0].toLocaleString() }} 入 / {{ m.tokens[1].toLocaleString() }} 出</span>
            </div>
            <template v-for="(b, i) in m.blocks" :key="i">
              <div v-if="b.type === 'tool'" class="tool">
                <Database v-if="b.name.startsWith('sql')" :size="13" /><SquareTerminal v-else :size="13" />
                <span class="mono">{{ b.name }}</span>
                <span v-if="b.args" class="mono muted ellipsis grow" :title="b.args">{{ b.args }}</span><span v-else class="grow" />
                <span class="mono t-ok">→ {{ b.result }}</span>
              </div>
            </template>
            <p v-if="m.text" class="txt">{{ m.text }}</p>
            <template v-for="(b, i) in m.blocks" :key="'b' + i">
              <div v-if="b.type === 'chart'" class="card">
                <div class="ch"><BarChart3 :size="14" />{{ b.title }}</div>
                <EChart :option="b.option()" :height="220" />
              </div>
              <div v-else-if="b.type === 'plan'" class="card">
                <div class="ch"><FileCode2 :size="14" />方案草稿 <span class="mono muted">{{ b.plan_id }}</span><span class="grow" />
                  <button class="btn btn-sm" @click="router.push('/plans')">在测试方案中打开<ChevronRight :size="14" /></button>
                </div>
                <div class="kv">
                  <div v-for="f in b.fields" :key="f[0]"><span class="mono">{{ f[0] }}</span><b class="num">{{ f[1] }}</b></div>
                </div>
              </div>
              <div v-else-if="b.type === 'action'" class="card act" :class="b.status">
                <div class="ch">
                  <span v-if="b.status === 'pending'" class="hz hazard" />
                  <Wrench :size="14" />{{ b.desc }}<span class="grow" />
                  <span v-if="b.status === 'pending'" class="tag warn">待确认</span>
                  <span v-else-if="b.status === 'done'" class="tag ok">已执行</span>
                  <span v-else class="tag">已拒绝</span>
                </div>
                <pre class="api"><b>{{ b.method }}</b> {{ b.path }}<template v-if="b.body">
{{ JSON.stringify(b.body, null, 2) }}</template></pre>
                <div v-if="b.status === 'pending'" class="row" style="padding: 0 10px 10px; justify-content: flex-end">
                  <button class="btn btn-sm" @click="reject(b)"><X :size="14" />拒绝</button>
                  <button class="btn btn-sm btn-primary" @click="approve(b)"><Check :size="14" />批准并执行</button>
                </div>
              </div>
            </template>
          </div>
        </div>
        <div v-if="busy" class="msg agent">
          <div class="av"><Bot :size="16" /></div>
          <div class="bd"><div class="row fs-sm muted"><Loader2 :size="14" class="spin" />正在查询本地库与集群…</div></div>
        </div>
      </div>
      <div class="composer">
        <textarea v-model="input" class="textarea" rows="2" placeholder="问数据、写方案、操作设备… Enter 发送，Shift+Enter 换行" @keydown.enter.exact.prevent="send()" />
        <button class="btn btn-primary btn-icon" :disabled="busy || !input.trim()" v-tip="'发送'" @click="send()"><ArrowUp :size="18" /></button>
      </div>
    </section>

    <!-- 右：上下文 -->
    <aside class="right">
      <Panel title="分析范围" code="SCOPE" :icon="Sparkles">
        <div class="field">
          <label>型号</label>
          <select v-model="scope.model" class="select">
            <option v-for="m in models" :key="m.model" :value="m.model">{{ m.model }}</option>
          </select>
        </div>
        <div class="field" style="margin-top: 10px">
          <label>批次（{{ scope.batches.length }}）</label>
          <label v-for="b in live.batchStats.filter((x) => x.model === scope.model)" :key="b.batch_id" class="bopt">
            <input type="checkbox" :checked="scope.batches.includes(b.batch_id)" @change="toggleBatch(b.batch_id)" />
            <span class="mono fs-xs grow ellipsis">{{ b.batch_id }}</span>
            <span class="num fs-xs muted">{{ ((b.passed / b.tested) * 100).toFixed(1) }}%</span>
          </label>
        </div>
        <p class="fs-xs muted" style="margin-top: 8px">方案：{{ plans.filter((p) => p.version).length }} 个已发布 · 机台：12 台</p>
      </Panel>
      <Panel title="待确认操作" code="PENDING" :icon="ShieldCheck" :accent="pending.length ? 'warn' : undefined" flush>
        <ul class="pend">
          <li v-for="(b, i) in pending" :key="i">
            <span class="mono fs-xs"><b>{{ b.method }}</b> {{ b.path }}</span>
            <span class="fs-sm">{{ b.desc }}</span>
            <div class="row" style="justify-content: flex-end">
              <button class="btn btn-sm btn-ghost" @click="reject(b)">拒绝</button>
              <button class="btn btn-sm btn-primary" @click="approve(b)">批准</button>
            </div>
          </li>
          <li v-if="!pending.length" class="none">没有待确认的操作</li>
        </ul>
      </Panel>
      <div class="usage">
        <span class="code-label">本次对话</span>
        <b class="num">{{ sessionTokens.toLocaleString() }}</b><span class="fs-xs muted">tokens</span>
        <button class="btn btn-ghost btn-sm" @click="router.push('/tokens')">统计<ChevronRight :size="14" /></button>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.agent { display: grid; grid-template-columns: 260px minmax(0, 1fr) 300px; height: 100%; min-height: 0; }
@media (max-width: 1360px) { .agent { grid-template-columns: 230px minmax(0, 1fr) 260px; } }
.left, .right { padding: 14px; display: flex; flex-direction: column; gap: 12px; overflow: auto; background: var(--c-surface); }
.left { border-right: var(--bw) solid var(--c-border); }
.right { border-left: var(--bw) solid var(--c-border); background: var(--c-bg); }
.cap h4 { display: flex; align-items: center; gap: 6px; font-size: var(--fs-sm); margin-bottom: 6px; }
.cap h4 .code-label { margin-left: auto; font-size: 9px; }
.pr { width: 100%; display: flex; align-items: center; gap: 4px; text-align: left; padding: 6px 8px; margin-bottom: 4px; border: var(--bw) solid var(--c-border); background: var(--c-surface-2); color: var(--c-text-2); font-size: var(--fs-xs); cursor: pointer; line-height: 1.4; }
.pr span { flex: 1; }
.pr:hover:not(:disabled) { border-color: var(--c-primary); color: var(--c-text); }
.safe { margin-top: auto; display: flex; gap: 8px; padding: 10px; background: var(--c-warn-weak); border-left: 3px solid var(--c-warn); font-size: var(--fs-xs); color: var(--c-text-2); line-height: 1.6; }
.safe svg { flex: none; color: var(--c-warn); }

.center { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.msgs { flex: 1; overflow: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 16px; }
.msg { display: flex; gap: 10px; max-width: 920px; }
.msg.user { align-self: flex-end; flex-direction: row-reverse; }
.av { width: 30px; height: 30px; flex: none; display: grid; place-items: center; background: var(--c-accent); color: #fff; }
.msg.user .av { background: var(--c-surface-3); color: var(--c-text-2); }
.bd { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 8px; }
.msg.user .bd { align-items: flex-end; }
.meta { display: flex; align-items: center; gap: 8px; font-size: var(--fs-xs); color: var(--c-text-3); }
.msg.user .meta { flex-direction: row-reverse; }
.txt { white-space: pre-wrap; line-height: 1.75; padding: 10px 12px; background: var(--c-surface); border: var(--bw) solid var(--c-border); }
.msg.user .txt { background: var(--c-primary-weak); border-color: color-mix(in srgb, var(--c-primary) 30%, transparent); }
.tool { display: flex; align-items: center; gap: 8px; padding: 4px 10px; font-size: var(--fs-xs); background: var(--c-surface-2); border-left: 2px solid var(--c-text-3); min-width: 0; }
.tool svg { flex: none; color: var(--c-text-3); }
.tool > .mono:first-of-type, .tool .t-ok { white-space: nowrap; }
.card { border: var(--bw) solid var(--c-border); background: var(--c-surface); }
.ch { display: flex; align-items: center; gap: 6px; padding: 8px 10px; font-weight: 600; font-size: var(--fs-sm); border-bottom: var(--bw) solid var(--c-border); position: relative; }
.kv { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--c-border); }
.kv div { display: flex; flex-direction: column; padding: 6px 10px; background: var(--c-surface); font-size: var(--fs-xs); color: var(--c-text-3); }
.kv b { color: var(--c-text); font-size: var(--fs-sm); }
.act.pending { border-color: var(--c-warn); }
.act.rejected { opacity: 0.6; }
.hz { position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }
.api { margin: 10px; padding: 8px 10px; background: var(--c-surface-2); border: var(--bw) solid var(--c-border); font-family: var(--font-mono); font-size: 12px; white-space: pre-wrap; }
.api b { color: var(--c-primary); }
.composer { display: flex; gap: 8px; align-items: flex-end; padding: 12px 20px 16px; border-top: var(--bw) solid var(--c-border); background: var(--c-surface); }
.composer .textarea { flex: 1; }
.spin { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.bopt { display: flex; align-items: center; gap: 6px; padding: 4px 0; cursor: pointer; font-weight: 400 !important; }
.bopt input { accent-color: var(--c-primary); }
.pend { list-style: none; margin: 0; padding: 0; }
.pend li { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border-bottom: var(--bw) solid var(--c-border); }
.pend .none { color: var(--c-text-3); font-size: var(--fs-sm); text-align: center; padding: 20px; }
.usage { display: flex; align-items: baseline; gap: 6px; padding: 10px 12px; background: var(--c-surface); border: var(--bw) solid var(--c-border); }
.usage b { font-size: var(--fs-lg); margin-left: auto; }
</style>
