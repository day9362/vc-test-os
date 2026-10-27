<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowUp, BarChart3, Bot, Check, ChevronRight, Database, FileCode2, Loader2, Plus, ShieldCheck, Sparkles, SquareTerminal, User, Wrench, X,
} from 'lucide-vue-next'
import Panel from '@/components/Panel.vue'
import EChart from '@/components/EChart.vue'
import { api } from '@/api/http'
import type { BatchStat } from '@/api/types'
import { useAppStore } from '@/stores/app'
import { hms } from '@/utils/format'

const app = useAppStore()
const route = useRoute()
const router = useRouter()

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
const input = ref('')
const busy = ref(false)
const scroller = ref<HTMLElement>()
const viewKey = ref(0)
const scope = ref({ model: '', batches: [] as string[], machines: [] as string[] })
const modelOptions = ref<{ model: string }[]>([])
const batchRows = ref<BatchStat[]>([])
const publishedPlans = ref(0)
const machineCount = ref(0)
const visibleBatches = computed(() => batchRows.value.filter((row) => row.model === scope.value.model))

function yieldText(row: BatchStat) {
  if (!row.tested) return '—'
  return `${((row.passed / row.tested) * 100).toFixed(1)}%`
}

async function loadScope() {
  const [modelRows, statPage, planRows, machineRows] = await Promise.all([
    api<{ model: string }[]>('/models'),
    api<{ items: BatchStat[] }>('/batch-stats?limit=50'),
    api<{ meta?: { draft?: boolean } }[]>('/plans'),
    api<{ machine_id: string }[]>('/machines'),
  ])
  modelOptions.value = modelRows
  batchRows.value = statPage.items || []
  publishedPlans.value = planRows.filter((row) => row.meta && !row.meta.draft).length
  machineCount.value = machineRows.length
  const preferred = modelOptions.value.find((row) => batchRows.value.some((batch) => batch.model === row.model))
  scope.value.model = preferred?.model || modelOptions.value[0]?.model || ''
  scope.value.batches = visibleBatches.value.slice(0, 3).map((row) => row.batch_id)
}

watch(() => scope.value.model, () => {
  scope.value.batches = visibleBatches.value.slice(0, 3).map((row) => row.batch_id)
})

const scroll = () => nextTick(() => scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' }))
type AgentModule = 'agent.analysis' | 'agent.plan' | 'agent.ops'
const MODULE_TEXT: Record<AgentModule, string> = { 'agent.analysis': '跨批次分析', 'agent.plan': '方案生成', 'agent.ops': '设备操作' }
const activeModule = ref<AgentModule>('agent.analysis')
const sessions = ref<Partial<Record<AgentModule, string>>>({})
const transcripts = ref<Record<AgentModule, Msg[]>>({
  'agent.analysis': [],
  'agent.plan': [],
  'agent.ops': [],
})
const msgs = computed(() => transcripts.value[activeModule.value])

function redraw() {
  viewKey.value += 1
  scroll()
}

async function showSession(module: AgentModule, force = false) {
  if (busy.value && !force) return
  activeModule.value = module
  const sid = sessions.value[module]
  if (!sid) {
    transcripts.value[module] = []
    redraw()
    return
  }
  const body = await api<{ messages: Msg[] }>(`/agent/sessions/${sid}`)
  transcripts.value[module] = (body.messages || []).map((item) => ({
    ...item,
    id: ++mid,
    blocks: item.blocks ?? [],
  }))
  redraw()
}

async function send(q = input.value, module?: AgentModule) {
  q = q.trim()
  if (!q || busy.value) return
  const chosen = module ?? activeModule.value
  if (chosen !== activeModule.value) await showSession(chosen)
  input.value = ''
  transcripts.value[chosen].push({ id: ++mid, role: 'user', text: q, blocks: [], time: Date.now() })
  busy.value = true
  scroll()
  try {
    let sid = sessions.value[chosen]
    if (!sid) {
      const created = await api<{ session_id: string }>('/agent/sessions', {
        method: 'POST',
        body: JSON.stringify({ module: chosen }),
      })
      sid = created.session_id
      sessions.value[chosen] = sid
    }
    await api<Msg>(`/agent/sessions/${sid}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text: q }),
    })
    await showSession(chosen, true)
  } catch (err) {
    app.toast({ kind: 'danger', title: 'Agent 没有完成', desc: err instanceof Error ? err.message : '请求失败' })
  } finally {
    busy.value = false
    scroll()
  }
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

function toggleBatch(id: string) {
  const s = scope.value.batches
  scope.value.batches = s.includes(id) ? s.filter((x) => x !== id) : [...s, id]
}
function newSession() {
  const module = activeModule.value
  delete sessions.value[module]
  transcripts.value[module] = []
  redraw()
}

onMounted(() => {
  loadScope().catch((err) => app.toast({ kind: 'danger', title: '分析范围没有加载', desc: err instanceof Error ? err.message : '请求失败' }))
  if (route.query.q) { send(String(route.query.q)); router.replace({ query: {} }) }
})
</script>

<template>
  <div class="agent">
    <!-- 左：能力 -->
    <aside class="left">
      <button class="btn btn-primary" style="width: 100%" @click="newSession"><Plus :size="16" />新对话</button>
      <div v-for="c in CAPS" :key="c.key" class="cap" :class="{ active: activeModule === c.module }">
        <h4 @click="showSession(c.module as AgentModule)"><component :is="c.icon" :size="14" />{{ c.title }}<span class="code-label">{{ c.module }}</span></h4>
        <button v-for="p in c.prompts" :key="p" class="pr" :disabled="busy" @click="send(p, c.module as AgentModule)">
          <span>{{ p }}</span><ChevronRight :size="14" />
        </button>
      </div>
      <div class="safe">
        <ShieldCheck :size="16" />
        <p>Agent 通过 vapor-chamber MCP 查看 mock 测试机，并直接下发方案、上下电和连续生产。请确认 MCP 服务和第三方模型地址已经配置。</p>
      </div>
    </aside>

    <!-- 中：对话 -->
    <section class="center">
      <div class="session-bar">
        <span class="tag primary">{{ MODULE_TEXT[activeModule] }}</span>
        <span class="mono fs-xs muted">{{ sessions[activeModule] || '新会话' }}</span>
      </div>
      <div :key="viewKey" ref="scroller" class="msgs">
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
          <div class="bd"><div class="row fs-sm muted"><Loader2 :size="14" class="spin" />正在通过 MCP 操作测试机…</div></div>
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
            <option v-for="m in modelOptions" :key="m.model" :value="m.model">{{ m.model }}</option>
          </select>
        </div>
        <div class="field" style="margin-top: 10px">
          <label>批次（{{ scope.batches.length }}）</label>
          <label v-for="b in visibleBatches" :key="b.batch_id" class="bopt">
            <input type="checkbox" :checked="scope.batches.includes(b.batch_id)" @change="toggleBatch(b.batch_id)" />
            <span class="mono fs-xs grow ellipsis">{{ b.batch_id }}</span>
            <span class="num fs-xs muted">{{ yieldText(b) }}</span>
          </label>
          <p v-if="!visibleBatches.length" class="fs-xs muted">这个型号还没有批次统计</p>
        </div>
        <p class="fs-xs muted" style="margin-top: 8px">方案：{{ publishedPlans }} 个已发布 · 机台：{{ machineCount }} 台</p>
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
.cap h4 { display: flex; align-items: center; gap: 6px; font-size: var(--fs-sm); margin-bottom: 6px; cursor: pointer; }
.cap.active h4 { color: var(--c-primary); }
.session-bar { display: flex; align-items: center; gap: 8px; padding: 8px 20px; border-bottom: var(--bw) solid var(--c-border); background: var(--c-surface); }
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
